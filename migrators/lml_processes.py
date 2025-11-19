r"""
Migrador para la colección lml_processes_mesa4core.

Implementa la interfaz BaseMigrator para transformar documentos de la
colección MongoDB 'lml_processes_mesa4core' al schema PostgreSQL 'lml_processes'.

Arquitectura:
- Hereda de BaseMigrator (contrato común)
- Métodos públicos: Interfaz requerida por mongomigra.py
- Métodos privados: Lógica específica de transformación

Uso (desde mongomigra.py):
    migrator = LMLProcessesMigrator(schema='lml_processes')
    
    shared = migrator.extract_shared_entities(doc, cursor, caches)
    data = migrator.extract_data(doc, shared)
    
    # Acumular en batches...
    migrator.insert_batches(batches, cursor)
"""

import config
from .base import BaseMigrator


class LmlProcessesMigrator(BaseMigrator):
    """
    Migrador específico para lml_processes_mesa4core.
    
    Transforma documentos con estructura de procesos/trámites desde MongoDB
    a un modelo relacional normalizado en PostgreSQL.
    
    Tablas destino:
    - {schema}.main: Registro principal del proceso
    - {schema}.movements: Historial de movimientos (1:N)
    - {schema}.initiator_fields: Campos dinámicos del iniciador (1:N)
    - {schema}.process_documents: Documentos asociados (1:N)
    - {schema}.last_movements: Último movimiento (1:1)
    
    Attributes:
        schema (str): Nombre del schema en PostgreSQL ('lml_processes')
    """
    
    def __init__(self, schema='lml_processes'):
        """
        Constructor del migrador.
        
        Args:
            schema: Nombre del schema destino en PostgreSQL
        """
        super().__init__(schema)
    
    # =========================================================================
    # MÉTODOS PÚBLICOS (INTERFAZ REQUERIDA)
    # =========================================================================
    
    def extract_shared_entities(self, doc, cursor, caches):
        """
        Extrae y procesa entidades compartidas (public.*).
        
        Implementa interfaz de BaseMigrator. Ver docstring en base.py para detalles.
        """
        result = {
            'created_by_user_id': self._extract_user_data(doc.get('createdBy'), cursor, caches),
            'updated_by_user_id': self._extract_user_data(doc.get('updatedBy'), cursor, caches),
            'customer_id': doc.get('customerId')
        }
        
        # Procesar customer
        self._extract_customer_data(result['customer_id'], cursor, caches)
        
        return result
    
    def extract_data(self, doc, shared_entities):
        """
        Extrae todos los datos del documento en estructura normalizada.
        
        Implementa interfaz de BaseMigrator. Retorna estructura compatible
        con initialize_batches() e insert_batches().
        """
        process_id = self.get_primary_key_from_doc(doc)
        
        # Extraer last_movement (puede ser None)
        last_movement = self._extract_last_movement(doc, process_id)
        
        return {
            'main': self._extract_main_record(doc, shared_entities),
            'related': {
                'movements': self._extract_movements(doc, process_id),
                'initiator_fields': self._extract_initiator_fields(doc, process_id),
                'documents': self._extract_documents(doc, process_id),
                'last_movements': [last_movement] if last_movement else []
            }
        }
    
    def insert_batches(self, batches, cursor):
        """
        Inserta todos los batches acumulados en PostgreSQL.
        
        Implementa interfaz de BaseMigrator.
        """
        # Insertar tabla main
        if batches['main']:
            self._insert_main_batch(batches['main'], cursor)
        
        # Insertar tablas relacionadas dinámicamente
        for table_name, records in batches['related'].items():
            if records:
                method_name = f'_insert_{table_name}_batch'
                insert_method = getattr(self, method_name)
                insert_method(records, cursor)
    
    def initialize_batches(self):
        """
        Retorna estructura vacía para acumular batches.
        
        Implementa interfaz de BaseMigrator. La estructura retornada es
        compatible con extract_data() e insert_batches().
        """
        return {
            'main': [],
            'related': {
                'movements': [],
                'initiator_fields': [],
                'documents': [],
                'last_movements': []
            }
        }
    
    def get_primary_key_from_doc(self, doc):
        """
        Extrae el process_id desde el documento MongoDB.
        
        Implementa interfaz de BaseMigrator.
        """
        return str(doc.get('_id'))
    
    # =========================================================================
    # MÉTODOS PRIVADOS (IMPLEMENTACIÓN INTERNA)
    # =========================================================================
    
    def _extract_user_data(self, user_obj, cursor, caches):
        """
        Extrae y normaliza datos de usuario desde un objeto user anidado.
        
        Esta función procesa la estructura típica de usuarios en lml_processes:
        
            {
              "user": {
                "id": "USR001",
                "email": "usuario@ejemplo.com",
                "area": { "id": "AREA01", "name": "Operaciones" },
                "subarea": { "id": "SUB01", "name": "Logística" },
                "role": { "id": "ROLE01", "name": "Gerente" },
                "groups": [{ "id": "GRP01", "name": "Admins" }]
              }
            }
        
        Args:
            user_obj: Objeto completo del tipo {"user": {...}} desde Mongo
            cursor: Cursor de psycopg2
            caches: Dict de sets para tracking
            
        Returns:
            str|None: user_id si se procesó, None si inválido
        """
        if not user_obj or 'user' not in user_obj or not user_obj['user']:
            return None
        
        user = user_obj['user']
        user_id = user.get('id')
        
        if not user_id:
            return None
        
        # Optimización: Si ya procesamos este usuario, retornar inmediatamente
        if user_id in caches['users']:
            return user_id
        
        tables = config.TABLE_NAMES
        
        # Procesar Area (si existe y no está en caché)
        if user.get('area') and user['area'].get('id'):
            area_id = user['area']['id']
            if area_id not in caches['areas']:
                cursor.execute(
                    f"INSERT INTO public.{tables['areas']} (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
                    (area_id, user['area'].get('name'))
                )
                caches['areas'].add(area_id)
        
        # Procesar Subarea
        if user.get('subarea') and user['subarea'].get('id'):
            subarea_id = user['subarea']['id']
            if subarea_id not in caches['subareas']:
                cursor.execute(
                    f"INSERT INTO public.{tables['subareas']} (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
                    (subarea_id, user['subarea'].get('name'))
                )
                caches['subareas'].add(subarea_id)
        
        # Procesar Role
        if user.get('role') and user['role'].get('id'):
            role_id = user['role']['id']
            if role_id not in caches['roles']:
                cursor.execute(
                    f"INSERT INTO public.{tables['roles']} (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
                    (role_id, user['role'].get('name'))
                )
                caches['roles'].add(role_id)
        
        # Insertar User principal
        cursor.execute(
            f"""INSERT INTO public.{tables['users']} 
                (id, email, firstname, lastname, area_id, subarea_id, role_id) 
                VALUES (%s, %s, %s, %s, %s, %s, %s) 
                ON CONFLICT (id) DO NOTHING;""",
            (
                user_id,
                user.get('email'),
                user.get('firstname'),
                user.get('lastname'),
                user.get('area', {}).get('id'),
                user.get('subarea', {}).get('id'),
                user.get('role', {}).get('id')
            )
        )
        caches['users'].add(user_id)
        
        # Procesar Groups y relación N:M con user
        if user.get('groups'):
            for group in user['groups']:
                if group and group.get('id'):
                    group_id = group['id']
                    
                    # Insertar group si no existe en caché
                    if group_id not in caches['groups']:
                        cursor.execute(
                            f"INSERT INTO public.{tables['groups']} (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
                            (group_id, group.get('name'))
                        )
                        caches['groups'].add(group_id)
                    
                    # Insertar relación user-group
                    cursor.execute(
                        f"INSERT INTO public.{tables['user_groups']} (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                        (user_id, group_id)
                    )
        
        return user_id
    
    def _extract_customer_data(self, customer_id, cursor, caches):
        """
        Inserta un customer_id en public.customers si no fue procesado.
        
        Args:
            customer_id: ID del cliente desde MongoDB
            cursor: Cursor de psycopg2
            caches: Dict de sets
        """
        if not customer_id or customer_id in caches['customers']:
            return
        
        tables = config.TABLE_NAMES
        cursor.execute(
            f"INSERT INTO public.{tables['customers']} (id) VALUES (%s) ON CONFLICT (id) DO NOTHING;",
            (customer_id,)
        )
        caches['customers'].add(customer_id)
    
    def _extract_main_record(self, doc, shared_entities):
        """
        Extrae el registro principal para la tabla main.
        
        Args:
            doc: Documento de MongoDB
            shared_entities: Dict con IDs de entidades compartidas
            
        Returns:
            tuple: Valores en orden de columnas de lml_processes.main
        """
        process_id = self.get_primary_key_from_doc(doc)
        starter = doc.get('processStarter', {})
        
        return (
            process_id,
            doc.get('processNumber'),
            doc.get('processTypeName'),
            doc.get('processAddress'),
            doc.get('processTypeId'),
            shared_entities['customer_id'],
            doc.get('deleted'),
            doc.get('createdAt'),
            doc.get('updatedAt'),
            doc.get('processDate'),
            doc.get('lumbreStatusName'),
            starter.get('id'),
            starter.get('name'),
            starter.get('starterType'),
            shared_entities['created_by_user_id'],
            shared_entities['updated_by_user_id']
        )
    
    def _extract_movements(self, doc, process_id):
        """
        Extrae la lista de movimientos del documento.
        
        Args:
            doc: Documento de MongoDB
            process_id: ID del proceso
            
        Returns:
            list[tuple]: Lista de movimientos
        """
        movements = []
        if doc.get('movements'):
            for movement in doc['movements']:
                movements.append((
                    process_id,
                    movement.get('at'),
                    movement.get('id'),
                    movement.get('to')
                ))
        return movements
    
    def _extract_initiator_fields(self, doc, process_id):
        """
        Extrae los campos dinámicos del iniciador del proceso.
        
        Args:
            doc: Documento de MongoDB
            process_id: ID del proceso
            
        Returns:
            list[tuple]: Lista de campos
        """
        fields = []
        if doc.get('initiatorFields'):
            for key, value in doc.get('initiatorFields').items():
                if isinstance(value, dict):
                    fields.append((
                        process_id,
                        key,
                        value.get('id'),
                        value.get('name')
                    ))
        return fields
    
    def _extract_documents(self, doc, process_id):
        """
        Extrae documentos externos e internos asociados al proceso.
        
        Args:
            doc: Documento de MongoDB
            process_id: ID del proceso
            
        Returns:
            list[tuple]: Lista de documentos
        """
        documents = []
        
        # Documentos externos
        if doc.get('documents'):
            for document in doc.get('documents'):
                if isinstance(document, dict):
                    documents.append((
                        process_id,
                        'external',
                        document.get('id')
                    ))
        
        # Documentos internos
        if doc.get('internalDocuments'):
            for document in doc.get('internalDocuments'):
                if isinstance(document, dict):
                    documents.append((
                        process_id,
                        'internal',
                        document.get('id')
                    ))
        
        return documents
    
    def _extract_last_movement(self, doc, process_id):
        """
        Extrae el último movimiento del proceso (relación 1:1).
        
        Args:
            doc: Documento de MongoDB
            process_id: ID del proceso
            
        Returns:
            tuple|None: Datos del último movimiento o None
        """
        if not doc.get('lastMovement'):
            return None
        
        lm = doc.get('lastMovement')
        origin_user = lm.get('origin', {}).get('user') or {}
        dest_user = lm.get('destination', {}).get('user') or {}
        
        origin_name = f"{origin_user.get('firstname', '')} {origin_user.get('lastname', '')}".strip()
        dest_name = f"{dest_user.get('firstname', '')} {dest_user.get('lastname', '')}".strip()
        
        return (
            process_id,
            origin_user.get('id'),
            origin_name,
            dest_user.get('id'),
            dest_name,
            dest_user.get('area', {}).get('name'),
            dest_user.get('subarea', {}).get('name')
        )
    
    def _insert_main_batch(self, batch, cursor):
        """
        Inserta batch de registros principales en la tabla main.
        
        Args:
            batch: Lista de tuples de _extract_main_record()
            cursor: Cursor de psycopg2
        """
        sql = f"""
            INSERT INTO {self.schema}.main 
            (process_id, process_number, process_type_name, process_address, 
             process_type_id, customer_id, deleted, created_at, updated_at, 
             process_date, lumbre_status_name, starter_id, starter_name, 
             starter_type, created_by_user_id, updated_by_user_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        cursor.executemany(sql, batch)
    
    def _insert_movements_batch(self, batch, cursor):
        """Inserta batch de movimientos."""
        cursor.executemany(
            f"INSERT INTO {self.schema}.movements (process_id, movement_at, destination_id, destination_type) VALUES (%s,%s,%s,%s)",
            batch
        )
    
    def _insert_initiator_fields_batch(self, batch, cursor):
        """Inserta batch de initiator fields."""
        cursor.executemany(
            f"INSERT INTO {self.schema}.initiator_fields (process_id, field_key, field_id, field_name) VALUES (%s,%s,%s,%s)",
            batch
        )
    
    def _insert_documents_batch(self, batch, cursor):
        """Inserta batch de documentos."""
        cursor.executemany(
            f"INSERT INTO {self.schema}.process_documents (process_id, doc_type, document_id) VALUES (%s,%s,%s)",
            batch
        )
    
    def _insert_last_movements_batch(self, batch, cursor):
        """Inserta batch de últimos movimientos."""
        cursor.executemany(
            f"""INSERT INTO {self.schema}.last_movements 
                (process_id, origin_user_id, origin_user_name, destination_user_id, 
                 destination_user_name, destination_area_name, destination_subarea_name) 
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            batch
        )