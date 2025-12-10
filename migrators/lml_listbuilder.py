"""
Migrador para la colección lml_listbuilder_mesa4core. 

Implementa la interfaz BaseMigrator para transformar configuraciones de UI
desde MongoDB al schema PostgreSQL 'lml_listbuilder'. 

RESPONSABILIDAD:
Este es un migrador de tipo 'consumer', lo que significa que:
- DEPENDE de lml_users (debe migrarse primero)
- NO inserta usuarios, solo extrae IDs y valida FKs
- Consume datos de snapshots (createdBy/updatedBy) para auditoría

A diferencia de lml_processes (datos transaccionales), esta colección almacena
metadata de cómo se renderizan las pantallas de listados en el frontend. 

Tablas destino:
- {schema}.main: Configuración principal del listado
- {schema}.fields: Columnas visibles (1:N)
- {schema}.available_fields: Pool de campos disponibles (1:N)
- {schema}.items: Items que se pueden mostrar (1:N)
- {schema}.button_links: Botones de acción (1:N)
- {schema}.path_actions: Acciones de navegación (1:N)
- {schema}.search_fields_selected: Campos de búsqueda seleccionados (1:N)
- {schema}.search_fields_to_selected: Campos de búsqueda alternativos (1:N)
- {schema}.privileges: Privilegios requeridos (1:N)
"""

import json
from datetime import datetime
from psycopg2.extras import execute_values
from .base import BaseMigrator
import config


class LmlListbuilderMigrator(BaseMigrator):
    """
    Migrador específico para lml_listbuilder_mesa4core.
    
    Transforma configuraciones UI (metadata) con múltiples arrays pequeños
    a un modelo relacional normalizado.
    
    Características:
    - Volumen bajo (~200 docs)
    - 9 tablas relacionadas (alta normalización)
    - Múltiples campos JSONB para flexibilidad
    """
    
    def __init__(self, schema='lml_listbuilder'):
        """
        Constructor del migrador.
        Args:
            schema: Nombre del schema destino en PostgreSQL
        """
        super().__init__(schema)
        # Cola en memoria para acumular usuarios fantasmas antes de insertar en lote
        self.ghost_users_queue = []
    
    # =========================================================================
    # MÉTODOS PÚBLICOS (INTERFAZ REQUERIDA)
    # =========================================================================
    
    def extract_shared_entities(self, doc, cursor, caches):
        """
        Extrae IDs. Si falta un usuario, lo guarda en memoria (cola) para insertarlo después.
        """
        # A. Cargar caché inicial de usuarios (Solo la primera vez, optimización masiva)
        if 'valid_user_ids' not in caches:
            try:
                # Cargamos TODOS los IDs existentes en RAM para comparar rápido
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
    
    def extract_data(self, doc, shared_entities):
        """
        Extrae todos los datos del documento en estructura normalizada.
        
        Implementa interfaz de BaseMigrator.
        """
        listbuilder_id = self.get_primary_key_from_doc(doc)
        
        return {
            'main': self._extract_main_record(doc, shared_entities),
            'related': {
                'fields': self._extract_fields(doc, listbuilder_id),
                'available_fields': self._extract_available_fields(doc, listbuilder_id),
                'items': self._extract_items(doc, listbuilder_id),
                'button_links': self._extract_button_links(doc, listbuilder_id),
                'path_actions': self._extract_path_actions(doc, listbuilder_id),
                'search_fields_selected': self._extract_search_fields_selected(doc, listbuilder_id),
                'search_fields_to_selected': self._extract_search_fields_to_selected(doc, listbuilder_id),
                'privileges': self._extract_privileges(doc, listbuilder_id)
            }
        }
    
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

        # --- Inserción Normal con execute_values ---
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
        
        Implementa interfaz de BaseMigrator.
        """
        return {
            'main': [],
            'related': {
                'fields': [],
                'available_fields': [],
                'items': [],
                'button_links': [],
                'path_actions': [],
                'search_fields_selected': [],
                'search_fields_to_selected': [],
                'privileges': []
            }
        }
    
    def get_primary_key_from_doc(self, doc):
        """
        Extrae el listbuilder_id desde el documento MongoDB.
        
        Implementa interfaz de BaseMigrador.
        """
        _id = doc.get('_id')
        if isinstance(_id, dict) and '$oid' in _id:
            return _id['$oid']
        return str(_id)
    
    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN DE IDS
    # =========================================================================
    
    def _process_ghost_user(self, snapshot, valid_users_set):
        """
        Verifica si el usuario existe. Si no, extrae sus datos y lo agrega a la cola de espera.
        """
        if not snapshot or not isinstance(snapshot, dict):
            return None
        
        user_data = snapshot.get('user', {})
        user_id = None
        
        # --- Extracción del ID ---
        if isinstance(user_data, (str, int)):
            user_id = str(user_data)
        elif isinstance(user_data, dict):
            user_id = user_data.get('id') or user_data.get('_id')
            if isinstance(user_id, dict): 
                user_id = user_id.get('$oid')
        
        if not user_id: 
            return None
            
        user_id = str(user_id)

        # Filtro de basura (IDs muy cortos no sirven)
        if len(user_id) < 5: 
            return None

        # --- LÓGICA CORE: COMPARACIÓN EN MEMORIA ---
        # Si NO está en el set de usuarios válidos, es un fantasma nuevo
        if user_id not in valid_users_set:
            
            # Preparamos los datos para restaurarlo
            firstname = None
            lastname = None
            email = None
            username = None
            
            if isinstance(user_data, dict):
                firstname = user_data.get('firstname') or user_data.get('firstName') or 'Restored'
                lastname = user_data.get('lastname') or user_data.get('lastName') or 'User'
                email = user_data.get('email')
                username = user_data.get('username') or user_data.get('userName')

            # 1. Agregamos a la COLA para insertar luego todos juntos
            # NOTA: Marcamos deleted=TRUE para diferenciarlo
            self.ghost_users_queue.append((user_id, firstname, lastname, email, username))
            
            # 2. Agregamos al SET inmediatamente para no duplicarlo en el mismo lote
            valid_users_set.add(user_id)
            
        return user_id
    
    # =========================================================================
    # MÉTODOS PRIVADOS - EXTRACCIÓN DE DATOS
    # =========================================================================
    
    def _extract_main_record(self, doc, shared_entities):
        """
        Extrae el registro principal para lml_listbuilder.main. 
        
        Campos JSONB se usan para estructura variable (softPermissions, etc).
        """
        listbuilder_id = self.get_primary_key_from_doc(doc)
        
        # Campos básicos
        alias = doc.get('alias')
        title_list = doc.get('titleList')
        gql_field = doc.get('gqlField')
        gql_query = doc.get('gqlQuery')
        
        # gqlVariables: dict → JSONB
        gql_variables = doc.get('gqlVariables')
        gql_variables_json = json.dumps(gql_variables) if gql_variables else None
        
        # mode: Objeto {table: bool, map: bool} → Dos columnas
        mode = doc.get('mode', {})
        mode_table = mode.get('table', True) if isinstance(mode, dict) else True
        mode_map = mode.get('map', False) if isinstance(mode, dict) else False
        
        # Metadata
        lumbre_internal = doc.get('lumbreInternal', False)
        lumbre_version = doc.get('lumbreVersion')
        selectable = doc.get('selectable')
        items_per_page = doc.get('itemsPerPage')
        page = doc.get('page')
        
        # Campos JSONB
        soft_permissions = doc.get('softPermissions')
        soft_permissions_json = json.dumps(soft_permissions) if soft_permissions else None
        
        aggs = doc.get('aggs')
        aggs_json = json.dumps(aggs) if aggs else None
        
        meta_search = doc.get('metaSearch')
        meta_search_json = json.dumps(meta_search) if meta_search else None
        
        mode_box_options = doc.get('modeBoxOptions')
        mode_box_options_json = json.dumps(mode_box_options) if mode_box_options else None
        
        # Timestamps
        created_at = self._parse_mongo_date(doc.get('createdAt'))
        updated_at = self._parse_mongo_date(doc.get('updatedAt'))
        
        # Relaciones
        customer_id = shared_entities['customer_id']
        created_by_user_id = shared_entities['created_by_user_id']
        updated_by_user_id = shared_entities['updated_by_user_id']
        
        # MongoDB __v
        mongo_version = doc.get('__v')
        
        return (
            listbuilder_id,
            alias,
            title_list,
            gql_field,
            gql_query,
            gql_variables_json,
            mode_table,
            mode_map,
            lumbre_internal,
            lumbre_version,
            selectable,
            items_per_page,
            page,
            soft_permissions_json,
            aggs_json,
            meta_search_json,
            mode_box_options_json,
            created_at,
            updated_at,
            created_by_user_id,
            updated_by_user_id,
            customer_id,
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
    
    def _extract_fields(self, doc, listbuilder_id):
        """Extrae el array 'fields' a registros de tabla."""
        fields = doc.get('fields', [])
        records = []
        
        for order, field in enumerate(fields):
            if not isinstance(field, dict):
                continue
            
            records.append((
                listbuilder_id,
                field.get('key'),
                field.get('label'),
                field.get('sortable', False),
                order
            ))
        
        return records
    
    def _extract_available_fields(self, doc, listbuilder_id):
        """Extrae el array 'allAvailableFields' a registros de tabla."""
        fields = doc.get('allAvailableFields', [])
        records = []
        
        for order, field in enumerate(fields):
            if not isinstance(field, dict):
                continue
            
            records.append((
                listbuilder_id,
                field.get('key'),
                field.get('label'),
                field.get('sortable', False),
                order
            ))
        
        return records
    
    def _extract_items(self, doc, listbuilder_id):
        """Extrae el array 'items' a registros de tabla."""
        items = doc.get('items', [])
        records = []
        
        for order, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            
            item_name = item.get('name')
            if item_name:
                records.append((
                    listbuilder_id,
                    item_name,
                    order
                ))
        
        return records
    
    def _extract_button_links(self, doc, listbuilder_id):
        """Extrae el array 'buttonLinks' a registros de tabla."""
        buttons = doc.get('buttonLinks', [])
        records = []
        
        for order, button in enumerate(buttons):
            if not isinstance(button, dict):
                continue
            
            records.append((
                listbuilder_id,
                button.get('value'),
                button.get('to'),
                button.get('buttonClass'),
                button.get('endpointToValidateVisibility'),
                button.get('show', True),
                button.get('disabled', False),
                order
            ))
        
        return records
    
    def _extract_path_actions(self, doc, listbuilder_id):
        """Extrae el array 'lmPathActions' a registros de tabla."""
        actions = doc.get('lmPathActions', [])
        records = []
        
        for order, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            
            records.append((
                listbuilder_id,
                action.get('to'),
                action.get('tooltip'),
                action.get('fontAwesomeIcon'),
                order
            ))
        
        return records
    
    def _extract_search_fields_selected(self, doc, listbuilder_id):
        """Extrae el array 'searchOnFieldsSelected' a registros de tabla."""
        fields = doc.get('searchOnFieldsSelected', [])
        records = []
        
        for order, field_name in enumerate(fields):
            if isinstance(field_name, str):
                records.append((
                    listbuilder_id,
                    field_name,
                    order
                ))
        
        return records
    
    def _extract_search_fields_to_selected(self, doc, listbuilder_id):
        """Extrae el array 'searchOnFieldsToSelected' a registros de tabla."""
        fields = doc.get('searchOnFieldsToSelected', [])
        records = []
        
        for order, field_name in enumerate(fields):
            if isinstance(field_name, str):
                records.append((
                    listbuilder_id,
                    field_name,
                    order
                ))
        
        return records
    
    def _extract_privileges(self, doc, listbuilder_id):
        """Extrae el array 'privileges' a registros de tabla."""
        privileges = doc.get('privileges', [])
        records = []
        
        for priv in privileges:
            if not isinstance(priv, dict):
                continue
            
            records.append((
                listbuilder_id,
                priv.get('id'),
                priv.get('name'),
                priv.get('codigo_privilegio')
            ))
        
        return records
    
    # =========================================================================
    # MÉTODOS PRIVADOS - INSERCIÓN DE DATOS (REFACTORIZADO CON execute_values)
    # =========================================================================
    
    def _insert_main_batch(self, records, cursor):
        """Inserta batch de registros en lml_listbuilder.main usando execute_values."""
        execute_values(
            cursor,
            """
            INSERT INTO lml_listbuilder.main (
                listbuilder_id, alias, title_list, gql_field, gql_query, gql_variables,
                mode_table, mode_map, lumbre_internal, lumbre_version, selectable,
                items_per_page, page, soft_permissions, aggs, meta_search, mode_box_options,
                created_at, updated_at, created_by_user_id, updated_by_user_id,
                customer_id, mongo_version
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=1000
        )
    
    def _insert_fields_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.fields usando execute_values."""
        execute_values(
            cursor,
            """
            INSERT INTO lml_listbuilder.fields (
                listbuilder_id, field_key, field_label, sortable, field_order
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s, %s, %s)",
            page_size=1000
        )
    
    def _insert_available_fields_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.available_fields usando execute_values."""
        execute_values(
            cursor,
            """
            INSERT INTO lml_listbuilder.available_fields (
                listbuilder_id, field_key, field_label, sortable, field_order
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s, %s, %s)",
            page_size=1000
        )
    
    def _insert_items_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.items usando execute_values."""
        execute_values(
            cursor,
            """
            INSERT INTO lml_listbuilder.items (
                listbuilder_id, item_name, item_order
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s)",
            page_size=1000
        )
    
    def _insert_button_links_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.button_links usando execute_values."""
        execute_values(
            cursor,
            """
            INSERT INTO lml_listbuilder.button_links (
                listbuilder_id, button_value, button_to, button_class,
                endpoint_to_validate_visibility, show_button, disabled, button_order
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=1000
        )
    
    def _insert_path_actions_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.path_actions usando execute_values."""
        execute_values(
            cursor,
            """
            INSERT INTO lml_listbuilder.path_actions (
                listbuilder_id, action_to, tooltip, font_awesome_icon, action_order
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s, %s, %s)",
            page_size=1000
        )
    
    def _insert_search_fields_selected_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.search_fields_selected usando execute_values."""
        execute_values(
            cursor,
            """
            INSERT INTO lml_listbuilder.search_fields_selected (
                listbuilder_id, field_name, field_order
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s)",
            page_size=1000
        )
    
    def _insert_search_fields_to_selected_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.search_fields_to_selected usando execute_values."""
        execute_values(
            cursor,
            """
            INSERT INTO lml_listbuilder.search_fields_to_selected (
                listbuilder_id, field_name, field_order
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s)",
            page_size=1000
        )
    
    def _insert_privileges_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.privileges usando execute_values."""
        execute_values(
            cursor,
            """
            INSERT INTO lml_listbuilder.privileges (
                listbuilder_id, privilege_id, privilege_name, privilege_code
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s, %s)",
            page_size=1000
        )