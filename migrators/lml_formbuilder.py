"""
Migrador para la colección lml_formbuilder_mesa4core. 

Implementa la interfaz BaseMigrator para transformar configuraciones de formularios
dinámicos desde MongoDB al schema PostgreSQL 'lml_formbuilder'. 

RESPONSABILIDAD:
Este es un migrador de tipo 'consumer', lo que significa que:
- DEPENDE de lml_users (debe migrarse primero)
- NO inserta usuarios, solo extrae IDs y valida FKs
- Consume datos de snapshots (createdBy/updatedBy) para auditoría

Características:
- Volumen: ~200 configuraciones de formularios
- Complejidad: formElements[] con avg 8.5 elementos, estructura profundamente anidada
- Arrays normalizados: formElements → tabla, privilegios → 3 tablas separadas
- JSONB: validations (55 estructuras), conditionals, soft_permissions

Tablas destino:
- {schema}.main: Configuración principal del formulario
- {schema}.elements: Elementos del formulario (campos, botones, etc.) - 1:N
- {schema}.allow_access: Privilegios de acceso - 1:N
- {schema}.allow_create: Privilegios de creación - 1:N
- {schema}.allow_update: Privilegios de actualización - 1:N
"""

import json
from datetime import datetime
from psycopg2.extras import execute_values
from .base import BaseMigrator
import config


class LmlFormbuilderMigrator(BaseMigrator):
    """
    Migrador específico para lml_formbuilder_mesa4core.
    
    Transforma configuraciones de formularios UI con elementos complejos
    y múltiples niveles de anidamiento a un modelo relacional normalizado.
    """
    
    def __init__(self, schema='lml_formbuilder'):
        """
        Constructor del migrador.
        Args:
            schema: Nombre del schema destino en PostgreSQL
        """
        super().__init__(schema)
        # Cola en memoria para acumular usuarios fantasmas antes de insertar en lote
        self.ghost_users_queue = []


    # =========================================================================
    # MÉTODOS PÚBLICOS - INTERFAZ REQUERIDA
    # =========================================================================
    
    def get_primary_key_from_doc(self, doc):
        """
        Extrae el formbuilder_id desde el documento MongoDB.
        
        Implementa interfaz de BaseMigrator.
        
        Args:
            doc: Documento MongoDB (dict)
            
        Returns:
            str: El _id convertido a string
        """
        _id = doc.get('_id')
        if isinstance(_id, dict) and '$oid' in _id:
            return _id['$oid']
        return str(_id)
    
    def initialize_batches(self):
        """
        Retorna estructura vacía para acumular batches.
        
        Implementa interfaz de BaseMigrator.
        
        La estructura refleja las tablas destino:
        - main: Tuplas para lml_formbuilder.main
        - related: Dict con arrays para cada tabla relacionada
        
        Returns:
            dict: Estructura de batches vacía
        """
        return {
            'main': [],
            'related': {
                'elements': [],
                'allow_access': [],
                'allow_create': [],
                'allow_update': []
            }
        }

    def extract_shared_entities(self, doc, cursor, caches):
        """
        Extrae IDs. Si falta un usuario, lo guarda en memoria (cola) para insertarlo después.
        """
        # A. Cargar caché inicial de usuarios (Solo la primera vez)
        if 'valid_user_ids' not in caches:
            try:
                cursor.execute("SELECT id FROM lml_users.main")
                caches['valid_user_ids'] = {row[0] for row in cursor.fetchall()}
            except Exception:
                caches['valid_user_ids'] = set()

        valid_users = caches['valid_user_ids']

        # B. Procesar createdBy/updatedBy usando la nueva lógica
        return {
            'created_by_user_id': self._process_ghost_user(doc.get('createdBy'), valid_users),
            'updated_by_user_id': self._process_ghost_user(doc.get('updatedBy'), valid_users),
            'customer_id': doc.get('customerId')
        }


    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN DE IDS (NUEVO)
    # =========================================================================
    
    def _process_ghost_user(self, snapshot, valid_users_set):
        """
        Verifica si el usuario existe. Si no, extrae sus datos y lo agrega a la cola de espera.
        """
        if not snapshot or not isinstance(snapshot, dict):
            return None
        
        user_data = snapshot.get('user', {})
        user_id = None
        
        # Extracción del ID
        if isinstance(user_data, (str, int)):
            user_id = str(user_data)
        elif isinstance(user_data, dict):
            user_id = user_data.get('id') or user_data.get('_id')
            if isinstance(user_id, dict): 
                user_id = user_id.get('$oid')
        
        if not user_id: return None
        user_id = str(user_id)

        # Filtro de basura (IDs muy cortos)
        if len(user_id) < 5: return None

        # --- LÓGICA CORE: COMPARACIÓN EN MEMORIA ---
        if user_id not in valid_users_set:
            
            # Preparamos datos para restaurar
            firstname = None
            lastname = None
            email = None
            username = None
            
            if isinstance(user_data, dict):
                firstname = user_data.get('firstname') or user_data.get('firstName') or 'Restored'
                lastname = user_data.get('lastname') or user_data.get('lastName') or 'User'
                email = user_data.get('email')
                username = user_data.get('username') or user_data.get('userName')

            # 1. Agregamos a la COLA
            self.ghost_users_queue.append((user_id, firstname, lastname, email, username))
            
            # 2. Agregamos al SET inmediatamente
            valid_users_set.add(user_id)
            
        return user_id


    def extract_data(self, doc, shared_entities):
        """
        Extrae todos los datos del documento en estructura normalizada.
        
        Implementa interfaz de BaseMigrator.
        
        Args:
            doc: Documento MongoDB completo
            shared_entities: Dict con IDs de entidades compartidas (del método anterior)
            
        Returns:
            dict: Estructura {
                'main': tupla para tabla main,
                'related': {
                    'elements': lista de tuplas,
                    'allow_access': lista de tuplas,
                    'allow_create': lista de tuplas,
                    'allow_update': lista de tuplas
                }
            }
        """
        formbuilder_id = self.get_primary_key_from_doc(doc)
        
        return {
            'main': self._extract_main_record(doc, shared_entities),
            'related': {
                'elements': self._extract_form_elements(doc, formbuilder_id),
                'allow_access': self._extract_privileges(doc, formbuilder_id, 'allowAccess'),
                'allow_create': self._extract_privileges(doc, formbuilder_id, 'allowCreate'),
                'allow_update': self._extract_privileges(doc, formbuilder_id, 'allowUpdate')
            }
        }


    # =========================================================================
    # MÉTODOS PRIVADOS - EXTRACCIÓN DE DATOS
    # =========================================================================
    
    def _extract_main_record(self, doc, shared_entities):
        """
        Extrae el registro principal para lml_formbuilder.main. 
        
        Maneja:
        - Campos escalares (strings, bools, ints)
        - Campos JSONB (dicts/arrays → json.dumps)
        - Timestamps (conversión de múltiples formatos)
        - FKs a entidades compartidas
        
        Args:
            doc: Documento MongoDB
            shared_entities: Dict con IDs extraídos de public.*
            
        Returns:
            tuple: Valores en orden de columnas de la tabla main
        """
        formbuilder_id = self.get_primary_key_from_doc(doc)
        
        # === Campos escalares ===
        alias = doc.get('alias')
        page_title_data = doc.get('pageTitleData')
        message_after_post_or_put = doc.get('messageAfterPOSTorPUT')
        path_to_redirect_after_post_or_put = doc.get('pathToRedirectAfterPOSTorPUT')
        api_rest_for_handle_all_http_methods = doc.get('apiRestForHandleAllHttpMethods')
        
        # === Campos JSONB (estructura variable) ===
        validations = doc.get('validations')
        validations_json = json.dumps(validations) if validations else None
        
        conditionals = doc.get('conditionals')
        conditionals_json = json.dumps(conditionals) if conditionals else None
        
        soft_permissions = doc.get('softPermissions')
        soft_permissions_json = json.dumps(soft_permissions) if soft_permissions else None
        
        # === Metadata Lumbre ===
        lumbre_internal = doc.get('lumbreInternal', False)
        lumbre_version = doc.get('lumbreVersion')
        
        # === Timestamps (2 campos diferentes en MongoDB) ===
        created = self._parse_mongo_date(doc.get('created'))
        created_at = self._parse_mongo_date(doc.get('createdAt'))
        updated_at = self._parse_mongo_date(doc.get('updatedAt'))
        
        # === Relaciones (FKs a public.*) ===
        customer_id = shared_entities['customer_id']
        created_by_user_id = shared_entities['created_by_user_id']
        updated_by_user_id = shared_entities['updated_by_user_id']
        
        # === Metadata MongoDB ===
        mongo_version = doc.get('__v')
        
        # Retornar tupla en orden de columnas de CREATE TABLE
        return (
            formbuilder_id,
            alias,
            page_title_data,
            message_after_post_or_put,
            path_to_redirect_after_post_or_put,
            api_rest_for_handle_all_http_methods,
            validations_json,
            conditionals_json,
            soft_permissions_json,
            lumbre_internal,
            lumbre_version,
            created,
            created_at,
            updated_at,
            customer_id,
            created_by_user_id,
            updated_by_user_id,
            mongo_version
        )

    def _parse_mongo_date(self, value):
        """
        Parsea Mongo Date a datetime de Python.
        
        Formatos soportados:
        - datetime nativo de pymongo
        - ISO8601 con 'Z': '2021-03-22T07:49:18.242Z'
        - ISO8601 con timezone: '2022-06-02T13:54:12.273+00:00'
        - Extended JSON: {'$date': '...'}
        
        Args:
            value: Valor del campo timestamp
        
        Returns:
            datetime|None: Timestamp parseado o None
        """
        if not value:
            return None
        
        try:
            # Caso 1: Ya es datetime
            if isinstance(value, datetime):
                return value
            
            # Caso 2: Extended JSON
            if isinstance(value, dict) and '$date' in value:
                value = value['$date']
            
            # Caso 3: String ISO8601
            if isinstance(value, str):
                # Con 'Z' al final
                if value.endswith('Z'):
                    if '.' in value:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
                    else:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                
                # Con timezone explícito
                if '+' in value or value.count('-') > 2:
                    return datetime.fromisoformat(value)
        
        except (ValueError, TypeError):
            return None
        
        return None

    def _extract_form_elements(self, doc, formbuilder_id):
        """
        Extrae el array 'formElements' a registros de tabla.
        
        Cada elemento puede tener múltiples campos JSONB con estructura
        variable dependiendo del tipo de componente (LmTextInput vs LmButton, etc). 
        
        Args:
            doc: Documento MongoDB
            formbuilder_id: ID del formbuilder (para FK)
            
        Returns:
            list: Lista de tuplas para lml_formbuilder.elements
        """
        elements = doc.get('formElements', [])
        records = []
        
        for order, elem in enumerate(elements):
            if not isinstance(elem, dict):
                continue
            
            # Campos escalares
            element_id = elem.get('id')
            component_name = elem.get('componentName')
            form_object_to_send_to_server_property = elem.get('formObjectToSendToServerProperty')
            class_name = elem.get('class')
            
            # Campos JSONB (estructura variable por tipo de componente)
            component_props = elem.get('componentProps')
            component_props_json = json.dumps(component_props) if component_props else None
            
            component_permissions = elem.get('componentPermissions')
            component_permissions_json = json.dumps(component_permissions) if component_permissions else None
            
            visibility_depend_on_conditions = elem.get('visibilityDependOnConditions')
            visibility_json = json.dumps(visibility_depend_on_conditions) if visibility_depend_on_conditions else None
            
            actions = elem.get('actions')
            actions_json = json.dumps(actions) if actions else None
            
            # Validations inline (diferente del validations global)
            validations = elem.get('validations')
            validations_json = json.dumps(validations) if validations else None
            
            # Configuración PDF
            is_hidden_on_pdf = elem.get('isHiddenOnPdf')
            has_label_on_pdf = elem.get('hasLabelOnPdf')
            
            records.append((
                formbuilder_id,
                element_id,
                component_name,
                form_object_to_send_to_server_property,
                class_name,
                component_props_json,
                component_permissions_json,
                visibility_json,
                actions_json,
                validations_json,
                is_hidden_on_pdf,
                has_label_on_pdf,
                order
            ))
        
        return records

    def _extract_privileges(self, doc, formbuilder_id, privilege_field):
        """
        Extrae arrays de privilegios (allowAccess, allowCreate, allowUpdate).
        
        Método genérico que procesa los 3 tipos de privilegios con la misma lógica.
        
        Args:
            doc: Documento MongoDB
            formbuilder_id: ID del formbuilder (para FK)
            privilege_field: Nombre del campo ('allowAccess', 'allowCreate', 'allowUpdate')
            
        Returns:
            list: Lista de tuplas para tablas de privilegios
        """
        privileges = doc.get(privilege_field, [])
        records = []
        
        for priv in privileges:
            if not isinstance(priv, dict):
                continue
            
            records.append((
                formbuilder_id,
                priv.get('id'),
                priv.get('name'),
                priv.get('codigo_privilegio')
            ))
        
        return records

    # =========================================================================
    # MÉTODOS PÚBLICOS - INSERCIÓN DE BATCHES
    # =========================================================================
    
    def insert_batches(self, batches, cursor, caches=None):
        """
        1. Inserta usuarios fantasmas acumulados (Bulk Insert).
        2. Inserta la data del formbuilder.
        """
        # --- PASO CRÍTICO: Insertar usuarios fantasmas pendientes ---
        if self.ghost_users_queue:
            try:
                execute_values(
                    cursor,
                    """
                    INSERT INTO lml_users.main 
                    (id, firstname, lastname, email, username, deleted, created_at, updated_at)
                    VALUES %s
                    ON CONFLICT (id) DO NOTHING
                    """,
                    self.ghost_users_queue,
                    template="(%s, %s, %s, %s, %s, TRUE, NOW(), NOW())",
                    page_size=1000
                )

                if caches and 'valid_user_ids' in caches:
                    caches['valid_user_ids'].update([u[0] for u in self.ghost_users_queue])

                self.ghost_users_queue = []
            except Exception as e:
                print(f"   ❌ Error insertando lote de ghost users: {e}")
        
        # 1. Insertar tabla main (debe ir primero por FKs)
        if batches['main']:
            self._insert_main_batch(batches['main'], cursor)
        
        # 2. Insertar tablas relacionadas
        for table_name, records in batches['related'].items():
            if records:
                method_name = f'_insert_{table_name}_batch'
                insert_method = getattr(self, method_name)
                insert_method(records, cursor)

    # =========================================================================
    # MÉTODOS PRIVADOS - INSERCIÓN POR TABLA
    # =========================================================================
    
    def _insert_main_batch(self, records, cursor):
        """
        Inserta batch en lml_formbuilder.main.
        
        Args:
            records: Lista de tuplas con valores para INSERT
            cursor: Cursor de psycopg2
        """
        cursor.executemany(f"""
            INSERT INTO {self.schema}.main (
                formbuilder_id,
                alias,
                page_title_data,
                message_after_post_or_put,
                path_to_redirect_after_post_or_put,
                api_rest_for_handle_all_http_methods,
                validations,
                conditionals,
                soft_permissions,
                lumbre_internal,
                lumbre_version,
                created,
                created_at,
                updated_at,
                customer_id,
                created_by_user_id,
                updated_by_user_id,
                mongo_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (formbuilder_id) DO NOTHING
        """, records)

    def _insert_elements_batch(self, records, cursor):
        """
        Inserta batch en lml_formbuilder.elements.
        
        Args:
            records: Lista de tuplas
            cursor: Cursor de psycopg2
        """
        cursor.executemany(f"""
            INSERT INTO {self.schema}.elements (
                formbuilder_id,
                element_id,
                component_name,
                form_object_to_send_to_server_property,
                class_name,
                component_props,
                component_permissions,
                visibility_depend_on_conditions,
                actions,
                validations,
                is_hidden_on_pdf,
                has_label_on_pdf,
                order_index
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, records)

    def _insert_allow_access_batch(self, records, cursor):
        """Inserta batch en lml_formbuilder.allow_access."""
        cursor.executemany(f"""
            INSERT INTO {self.schema}.allow_access (
                formbuilder_id,
                privilege_id,
                name,
                codigo_privilegio
            ) VALUES (%s, %s, %s, %s)
        """, records)
    
    def _insert_allow_create_batch(self, records, cursor):
        """Inserta batch en lml_formbuilder.allow_create."""
        cursor.executemany(f"""
            INSERT INTO {self.schema}.allow_create (
                formbuilder_id,
                privilege_id,
                name,
                codigo_privilegio
            ) VALUES (%s, %s, %s, %s)
        """, records)
    
    def _insert_allow_update_batch(self, records, cursor):
        """Inserta batch en lml_formbuilder.allow_update."""
        cursor.executemany(f"""
            INSERT INTO {self.schema}.allow_update (
                formbuilder_id,
                privilege_id,
                name,
                codigo_privilegio
            ) VALUES (%s, %s, %s, %s)
        """, records)