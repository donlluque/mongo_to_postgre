"""
Migrador para la colección lml_users_mesa4core. 

Implementa la interfaz BaseMigrator para transformar documentos de usuarios
desde MongoDB hacia el schema PostgreSQL 'lml_users'. 

RESPONSABILIDAD:
Este es un migrador de tipo 'truth_source', lo que significa que:
- NO consume datos de otros schemas (extract_shared_entities retorna vacío)
- ES la fuente de verdad para usuarios y catálogos embebidos
- Otros migradores (processes, listbuilder, etc.) referencian estos datos vía FK

ARQUITECTURA DEL SCHEMA lml_users:
- main: Datos principales de usuarios (6 tablas total)
- roles, areas, subareas, positions, signaturetypes: Catálogos embebidos

DECISIONES DE DISEÑO:
- Catálogos con UPSERT (DO UPDATE): Permite corrección de nombres
- Usuarios con UPSERT (DO NOTHING): Preserva primer insert completo
- Timestamps dual: Priorizar createdAt/updatedAt sobre created_at/updated_at
- Campos opcionales: username, position_id, signaturetype_id → NULL
- Typo conocido: useerType vs userType → manejar ambos

Uso (desde mongomigra.py):
    migrator = LmlUsersMigrator(schema='lml_users')
    
    shared = migrator.extract_shared_entities(doc, cursor, caches)  # {}
    data = migrator.extract_data(doc, shared)
    
    # Acumular en batches... 
    migrator.insert_batches(batches, cursor)
"""

from datetime import datetime
from .base import BaseMigrator
from psycopg2.extras import execute_values
import config


class LmlUsersMigrator(BaseMigrator):
    """
    Migrador específico para lml_users_mesa4core.
    
    Transforma documentos de usuarios con catálogos embebidos desde MongoDB
    a un modelo relacional normalizado en PostgreSQL.
    
    Tablas destino:
    - {schema}.main: Datos principales del usuario
    - {schema}.roles: Catálogo de roles
    - {schema}.areas: Catálogo de áreas organizacionales
    - {schema}.subareas: Catálogo de subáreas
    - {schema}.positions: Catálogo de posiciones
    - {schema}.signaturetypes: Catálogo de tipos de firma
    
    Attributes:
        schema (str): Nombre del schema en PostgreSQL ('lml_users')
    """
    
    def __init__(self, schema='lml_users'):
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
        Extrae entidades compartidas (public.*). 
        
        Para migradores truth_source, este método retorna dict vacío
        porque NO consumen datos de otros schemas.
        
        Args:
            doc: Documento de MongoDB
            cursor: Cursor de psycopg2 (no usado en truth_source)
            caches: Dict de sets (no usado en truth_source)
        
        Returns:
            dict: Dict vacío (truth_source no tiene upstream dependencies)
        """
        return {}
    
    def extract_data(self, doc, shared_entities):
        """
        Extrae todos los datos del documento en estructura normalizada.
        
        Proceso:
        1. Extraer catálogos embebidos (role, area, subarea, position, signaturetype)
        2. Extraer datos del usuario principal
        3. Normalizar timestamps (priorizar Mongo Date sobre string legacy)
        4. Manejar campos opcionales y typo useerType
        
        Args:
            doc: Documento de MongoDB
            shared_entities: Dict vacío (no usado en truth_source)
        
        Returns:
            dict: Estructura con usuario y catálogos:
                {
                    'main': tuple con datos del usuario,
                    'related': {
                        'roles': [tuple(id, name)],
                        'areas': [tuple(id, name, descripcion)],
                        'subareas': [tuple(id, name)],
                        'positions': [tuple(id, name)],
                        'signaturetypes': [tuple(id, name, descripcion)]
                    }
                }
        """
        user_id = self.get_primary_key_from_doc(doc)
        
        # Extraer catálogos embebidos
        role = self._extract_catalog_role(doc)
        area = self._extract_catalog_area(doc)
        subarea = self._extract_catalog_subarea(doc)
        position = self._extract_catalog_position(doc)
        signaturetype = self._extract_catalog_signaturetype(doc)
        
        return {
            'main': self._extract_main_record(doc),
            'related': {
                'roles': [role] if role else [],
                'areas': [area] if area else [],
                'subareas': [subarea] if subarea else [],
                'positions': [position] if position else [],
                'signaturetypes': [signaturetype] if signaturetype else []
            }
        }
    
    def insert_batches(self, batches, cursor, caches=None):
        """
        Inserta todos los batches acumulados en PostgreSQL.
        
        ORDEN CRÍTICO:
        1. Catálogos primero (UPSERT con DO UPDATE)
        2. Usuarios después (UPSERT con DO NOTHING)
        
        Justificación: lml_users.main tiene FKs a catálogos, deben existir primero.
        
        Args:
            batches: Dict con estructura de initialize_batches()
            cursor: Cursor de psycopg2
        """
        # Paso 1: UPSERT catálogos (permite corrección de nombres)
        if batches['related']['roles']:
            # Deduplicar por ID (primer elemento de la tupla)
            unique_roles = list({role[0]: role for role in batches['related']['roles']}.values())
            self._insert_roles_batch(unique_roles, cursor)
        
        if batches['related']['areas']:
            unique_areas = list({area[0]: area for area in batches['related']['areas']}.values())
            self._insert_areas_batch(unique_areas, cursor)
        
        if batches['related']['subareas']:
            unique_subareas = list({subarea[0]: subarea for subarea in batches['related']['subareas']}.values())
            self._insert_subareas_batch(unique_subareas, cursor)
        
        if batches['related']['positions']:
            unique_positions = list({pos[0]: pos for pos in batches['related']['positions']}.values())
            self._insert_positions_batch(unique_positions, cursor)
        
        if batches['related']['signaturetypes']:
            unique_sigtypes = list({sig[0]: sig for sig in batches['related']['signaturetypes']}.values())
            self._insert_signaturetypes_batch(unique_sigtypes, cursor)
        
        # Paso 2: UPSERT usuarios (DO NOTHING para idempotencia)
        if batches['main']:
            # Los usuarios también pueden tener duplicados (aunque menos probable)
            unique_users = list({user[0]: user for user in batches['main']}.values())
            self._insert_main_batch(unique_users, cursor)
    
    def initialize_batches(self):
        """
        Retorna estructura vacía para acumular batches.
        
        Returns:
            dict: Estructura compatible con extract_data() e insert_batches()
        """
        return {
            'main': [],
            'related': {
                'roles': [],
                'areas': [],
                'subareas': [],
                'positions': [],
                'signaturetypes': []
            }
        }
    
    def get_primary_key_from_doc(self, doc):
        """
        Extrae el user_id desde el documento MongoDB.
        
        Args:
            doc: Documento de MongoDB
        
        Returns:
            str: ID del usuario
        """
        return str(doc.get('_id'))
    
    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN DE CATÁLOGOS
    # =========================================================================
    
    def _extract_catalog_role(self, doc):
        """
        Extrae catálogo role del documento. 
        
        Args:
            doc: Documento MongoDB
        
        Returns:
            tuple|None: (id, name) o None si no existe
        """
        role = doc.get('role', {})
        if isinstance(role, dict) and role.get('id'):
            return (
                role['id'],
                role.get('name')
            )
        return None
    
    def _extract_catalog_area(self, doc):
        """
        Extrae catálogo area del documento.
        
        Args:
            doc: Documento MongoDB
        
        Returns:
            tuple|None: (id, name, descripcion) o None si no existe
        """
        area = doc.get('area', {})
        if isinstance(area, dict) and area.get('id'):
            return (
                area['id'],
                area.get('name'),
                area.get('descripcion')  # Puede ser None
            )
        return None
    
    def _extract_catalog_subarea(self, doc):
        """
        Extrae catálogo subarea del documento.
        
        Args:
            doc: Documento MongoDB
        
        Returns:
            tuple|None: (id, name) o None si no existe
        """
        subarea = doc.get('subarea', {})
        if isinstance(subarea, dict) and subarea.get('id'):
            return (
                subarea['id'],
                subarea.get('name')
            )
        return None
    
    def _extract_catalog_position(self, doc):
        """
        Extrae catálogo position del documento.
        
        Args:
            doc: Documento MongoDB
        
        Returns:
            tuple|None: (id, name) o None si no existe
        """
        position = doc.get('position', {})
        if isinstance(position, dict) and position.get('id'):
            return (
                position['id'],
                position.get('name')
            )
        return None
    
    def _extract_catalog_signaturetype(self, doc):
        """
        Extrae catálogo signaturetype del documento. 
        
        Args:
            doc: Documento MongoDB
        
        Returns:
            tuple|None: (id, name, descripcion) o None si no existe
        """
        signaturetype = doc.get('signaturetype', {})
        if isinstance(signaturetype, dict) and signaturetype.get('id'):
            return (
                signaturetype['id'],
                signaturetype.get('name'),
                signaturetype.get('descripcion')  # Puede ser None
            )
        return None
    
    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN DE USUARIO PRINCIPAL
    # =========================================================================
    
    def _extract_main_record(self, doc):
        """
        Extrae el registro principal para la tabla main.
        
        IMPORTANTE: El orden de los campos debe coincidir EXACTAMENTE con
        el orden de columnas en el INSERT de _insert_main_batch().
        
        Args:
            doc: Documento de MongoDB
        
        Returns:
            tuple: Valores en orden de columnas de lml_users.main
        """
        user_id = self.get_primary_key_from_doc(doc)
        
        # Extraer IDs de catálogos (pueden ser None)
        role_id = doc.get('role', {}).get('id') if isinstance(doc.get('role'), dict) else None
        area_id = doc.get('area', {}).get('id') if isinstance(doc.get('area'), dict) else None
        subarea_id = doc.get('subarea', {}).get('id') if isinstance(doc.get('subarea'), dict) else None
        position_id = doc.get('position', {}).get('id') if isinstance(doc.get('position'), dict) else None
        signaturetype_id = doc.get('signaturetype', {}).get('id') if isinstance(doc.get('signaturetype'), dict) else None
        
        # Normalizar timestamps
        created_at = self._extract_timestamp(doc, 'createdAt', 'created_at')
        updated_at = self._extract_timestamp(doc, 'updatedAt', 'updated_at')
        
        # Extraer updated_by_user_id de auditoría
        updated_by_user_id = self._extract_updated_by_user_id(doc)
        
        # Normalizar customer_id (puede venir como customer_id o customerId)
        customer_id = doc.get('customer_id') or doc.get('customerId')
        
        # Normalizar campos con posible camelCase
        lumbre_version = doc.get('lumbre_version') or doc.get('lumbreVersion')
        license_status = doc.get('license_status') or doc.get('licenseStatus')
        
        return (
            user_id,
            doc.get('firstname'),
            doc.get('lastname'),
            doc.get('username'),  # Puede ser None
            doc.get('email'),
            doc.get('password'),  # Puede ser None
            role_id,
            area_id,
            subarea_id,
            position_id,
            signaturetype_id,
            customer_id,
            doc.get('deleted', False),
            self._extract_user_type(doc),
            license_status,
            doc.get('signature'),
            doc.get('dni'),
            lumbre_version,
            created_at,
            updated_at,
            updated_by_user_id,
            doc.get('__v')
        )
    
    # =========================================================================
    # MÉTODOS PRIVADOS: HELPERS DE NORMALIZACIÓN
    # =========================================================================
    
    def _extract_timestamp(self, doc, primary_field, fallback_field):
        """
        Extrae timestamp priorizando Mongo Date sobre string legacy.
        
        Estrategia:
        1. Intentar primary_field (createdAt/updatedAt - Mongo Date)
        2. Si falla, intentar fallback_field (created_at/updated_at - string)
        
        Args:
            doc: Documento MongoDB
            primary_field: Campo preferido (ej: 'createdAt')
            fallback_field: Campo fallback (ej: 'created_at')
        
        Returns:
            datetime|None: Timestamp parseado o None
        """
        # Prioridad 1: Mongo Date
        value = doc.get(primary_field)
        if value:
            parsed = self._parse_mongo_date(value)
            if parsed:
                return parsed
        
        # Prioridad 2: String legacy
        value = doc.get(fallback_field)
        if value:
            return self._parse_string_date(value)
        
        return None
    
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
            # Caso 1: Ya es datetime (pymongo lo convierte automáticamente)
            if isinstance(value, datetime):
                return value
            
            # Caso 2: Extended JSON
            if isinstance(value, dict) and '$date' in value:
                value = value['$date']
            
            # Caso 3: String con formato ISO8601
            if isinstance(value, str):
                # Intentar con 'Z' al final
                if value.endswith('Z'):
                    if '.' in value:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
                    else:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                
                # Intentar con timezone explícito (+00:00, +05:30, etc.)
                if '+' in value or value.count('-') > 2:  # Detectar timezone
                    # Python 3.7+ soporta este formato directamente
                    return datetime.fromisoformat(value)
        
        except (ValueError, TypeError):
            return None
        
        return None
    
    def _parse_string_date(self, value):
        """
        Parsea string legacy a datetime. 
        
        Formato esperado: '2025-01-15T10:30:00Z' (sin milisegundos)
        
        Args:
            value: String con timestamp
        
        Returns:
            datetime|None: Timestamp parseado o None
        """
        if not isinstance(value, str):
            return None
        
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None
    
    def _extract_user_type(self, doc):
        """
        Extrae userType manejando el typo conocido useerType.
        
        Args:
            doc: Documento MongoDB
        
        Returns:
            str|None: Tipo de usuario
        """
        # Priorizar campo correcto
        user_type = doc.get('userType')
        if user_type:
            return user_type
        
        # Fallback al typo
        return doc.get('useerType')
    
    def _extract_updated_by_user_id(self, doc):
        """
        Extrae ID de usuario que hizo la última actualización.
        
        Busca en: updatedBy.user.id
        
        Args:
            doc: Documento MongoDB
        
        Returns:
            str|None: ID del usuario o None
        """
        updated_by = doc.get('updatedBy', {})
        if isinstance(updated_by, dict):
            user = updated_by.get('user', {})
            if isinstance(user, dict):
                return user.get('id')
        return None
    
    # =========================================================================
    # MÉTODOS PRIVADOS: INSERCIÓN DE BATCHES
    # =========================================================================

    def _insert_roles_batch(self, batch, cursor):
        """Inserta roles usando execute_values (Optimizado)."""
        execute_values(cursor, f"""
            INSERT INTO {self.schema}.roles (id, name) VALUES %s
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
        """, batch)

    def _insert_areas_batch(self, batch, cursor):
        """Inserta areas usando execute_values (Optimizado)."""
        execute_values(cursor, f"""
            INSERT INTO {self.schema}.areas (id, name, descripcion) VALUES %s
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, descripcion = EXCLUDED.descripcion
        """, batch)

    def _insert_subareas_batch(self, batch, cursor):
        """Inserta subareas usando execute_values (Optimizado)."""
        execute_values(cursor, f"""
            INSERT INTO {self.schema}.subareas (id, name) VALUES %s
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
        """, batch)

    def _insert_positions_batch(self, batch, cursor):
        """Inserta positions usando execute_values (Optimizado)."""
        execute_values(cursor, f"""
            INSERT INTO {self.schema}.positions (id, name) VALUES %s
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
        """, batch)

    def _insert_signaturetypes_batch(self, batch, cursor):
        """Inserta signaturetypes usando execute_values (Optimizado)."""
        execute_values(cursor, f"""
            INSERT INTO {self.schema}.signaturetypes (id, name, descripcion) VALUES %s
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, descripcion = EXCLUDED.descripcion
        """, batch)

    def _insert_main_batch(self, batch, cursor):
        """Inserta usuarios principales usando execute_values (Optimizado)."""
        execute_values(cursor, f"""
            INSERT INTO {self.schema}.main 
            (id, firstname, lastname, username, email, password,
             role_id, area_id, subarea_id, position_id, signaturetype_id,
             customer_id, deleted, user_type, license_status, signature, dni,
             lumbre_version, created_at, updated_at, updated_by_user_id, __v)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
        """, batch, page_size=1000)