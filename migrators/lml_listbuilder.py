"""
Migrador para la colección lml_listbuilder_mesa4core.

Implementa la interfaz BaseMigrator para transformar configuraciones de UI
desde MongoDB al schema PostgreSQL 'lml_listbuilder'.

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
from .base import BaseMigrator
import config


class LmlListbuilderMigrator(BaseMigrator):
    """
    Migrador específico para lml_listbuilder_mesa4core.
    
    Transforma configuraciones UI (metadata) con múltiples arrays pequeños
    a un modelo relacional normalizado.
    
    Características:
    - Volumen bajo (~200 docs)
    - 8 tablas relacionadas (alta normalización)
    - Múltiples campos JSONB para flexibilidad
    """
    
    def __init__(self, schema='lml_listbuilder'):
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
        
        Implementa interfaz de BaseMigrator.
        """
        result = {
            'customer_id': None,
            'created_by_user_id': None,
            'updated_by_user_id': None
        }
        
        # Customer ID (presente en todos los docs)
        customer_id = doc.get('customerId')
        if customer_id and customer_id not in caches['customers']:
            cursor.execute(
                "INSERT INTO public.customers (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                (customer_id,)
            )
            caches['customers'].add(customer_id)
        result['customer_id'] = customer_id
        
        # CreatedBy user
        created_by = doc.get('createdBy', {})
        if created_by:
            user_id = self._extract_user_id_from_action(created_by)
            if user_id:
                self._insert_user_if_needed(created_by.get('user', {}), cursor, caches)
                result['created_by_user_id'] = str(user_id)
        
        # UpdatedBy user
        updated_by = doc.get('updatedBy', {})
        if updated_by:
            user_id = self._extract_user_id_from_action(updated_by)
            if user_id:
                self._insert_user_if_needed(updated_by.get('user', {}), cursor, caches)
                result['updated_by_user_id'] = str(user_id)
        
        return result
    
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
        
        Implementa interfaz de BaseMigrator.
        """
        _id = doc.get('_id')
        if isinstance(_id, dict) and '$oid' in _id:
            return _id['$oid']
        return str(_id)
    
    # =========================================================================
    # MÉTODOS PRIVADOS - PROCESAMIENTO DE USUARIOS
    # =========================================================================
    
    def _extract_user_id_from_action(self, action_obj):
        """
        Extrae el ID de usuario de un objeto createdBy/updatedBy.
        
        La estructura puede variar entre documentos.
        """
        if not action_obj or not isinstance(action_obj, dict):
            return None
        
        user = action_obj.get('user', {})
        
        # Caso 1: user es directamente un string/int (ID)
        if isinstance(user, (str, int)):
            return user
        
        # Caso 2: user es un objeto con campo 'id' o '_id'
        if isinstance(user, dict):
            user_id = user.get('id')
            if user_id:
                return user_id
            
            mongo_id = user.get('_id')
            if mongo_id:
                if isinstance(mongo_id, dict):
                    return mongo_id.get('$oid')
                return mongo_id
        
        return None
    
    def _insert_user_if_needed(self, user_obj, cursor, caches):
        """
        Inserta un usuario en public.users si no existe.
        
        Maneja estructura completa con relaciones (area, subarea, role).
        """
        if not user_obj or not isinstance(user_obj, dict):
            return
        
        user_id = user_obj.get('id')
        if not user_id or user_id in caches['users']:
            return
        
        # Extraer relaciones
        area = user_obj.get('area', {})
        area_id = area.get('id') if isinstance(area, dict) else None
        
        subarea = user_obj.get('subarea', {})
        subarea_id = subarea.get('id') if isinstance(subarea, dict) else None
        
        role = user_obj.get('role', {})
        role_id = role.get('id') if isinstance(role, dict) else None
        
        # Insertar entidades relacionadas
        if area_id and area_id not in caches['areas']:
            cursor.execute(
                "INSERT INTO public.areas (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (area_id, area.get('name'))
            )
            caches['areas'].add(area_id)
        
        if subarea_id and subarea_id not in caches['subareas']:
            cursor.execute(
                "INSERT INTO public.subareas (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (subarea_id, subarea.get('name'))
            )
            caches['subareas'].add(subarea_id)
        
        if role_id and role_id not in caches['roles']:
            cursor.execute(
                "INSERT INTO public.roles (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (role_id, role.get('name'))
            )
            caches['roles'].add(role_id)
        
        # Insertar usuario
        cursor.execute("""
            INSERT INTO public.users (id, email, firstname, lastname, area_id, subarea_id, role_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            str(user_id),
            user_obj.get('email'),
            user_obj.get('firstname'),
            user_obj.get('lastname'),
            area_id,
            subarea_id,
            role_id
        ))
        
        caches['users'].add(user_id)
    
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
    
    def _parse_mongo_date(self, date_value):
        """Parsea fechas de MongoDB en múltiples formatos."""
        if not date_value:
            return None
        
        # Formato Extended JSON: {'$date': '...'}
        if isinstance(date_value, dict) and '$date' in date_value:
            date_value = date_value['$date']
        
        # String ISO8601
        if isinstance(date_value, str):
            try:
                if '.' in date_value:
                    return datetime.strptime(date_value, "%Y-%m-%dT%H:%M:%S.%fZ")
                else:
                    return datetime.strptime(date_value, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
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
    # MÉTODOS PRIVADOS - INSERCIÓN DE DATOS
    # =========================================================================
    
    def _insert_main_batch(self, records, cursor):
        """Inserta batch de registros en lml_listbuilder.main."""
        cursor.executemany("""
            INSERT INTO lml_listbuilder.main (
                listbuilder_id, alias, title_list, gql_field, gql_query, gql_variables,
                mode_table, mode_map, lumbre_internal, lumbre_version, selectable,
                items_per_page, page, soft_permissions, aggs, meta_search, mode_box_options,
                created_at, updated_at, created_by_user_id, updated_by_user_id,
                customer_id, mongo_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
        """, records)
    
    def _insert_fields_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.fields."""
        cursor.executemany("""
            INSERT INTO lml_listbuilder.fields (
                listbuilder_id, field_key, field_label, sortable, field_order
            ) VALUES (%s, %s, %s, %s, %s)
        """, records)
    
    def _insert_available_fields_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.available_fields."""
        cursor.executemany("""
            INSERT INTO lml_listbuilder.available_fields (
                listbuilder_id, field_key, field_label, sortable, field_order
            ) VALUES (%s, %s, %s, %s, %s)
        """, records)
    
    def _insert_items_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.items."""
        cursor.executemany("""
            INSERT INTO lml_listbuilder.items (
                listbuilder_id, item_name, item_order
            ) VALUES (%s, %s, %s)
        """, records)
    
    def _insert_button_links_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.button_links."""
        cursor.executemany("""
            INSERT INTO lml_listbuilder.button_links (
                listbuilder_id, button_value, button_to, button_class,
                endpoint_to_validate_visibility, show_button, disabled, button_order
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, records)
    
    def _insert_path_actions_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.path_actions."""
        cursor.executemany("""
            INSERT INTO lml_listbuilder.path_actions (
                listbuilder_id, action_to, tooltip, font_awesome_icon, action_order
            ) VALUES (%s, %s, %s, %s, %s)
        """, records)
    
    def _insert_search_fields_selected_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.search_fields_selected."""
        cursor.executemany("""
            INSERT INTO lml_listbuilder.search_fields_selected (
                listbuilder_id, field_name, field_order
            ) VALUES (%s, %s, %s)
        """, records)
    
    def _insert_search_fields_to_selected_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.search_fields_to_selected."""
        cursor.executemany("""
            INSERT INTO lml_listbuilder.search_fields_to_selected (
                listbuilder_id, field_name, field_order
            ) VALUES (%s, %s, %s)
        """, records)
    
    def _insert_privileges_batch(self, records, cursor):
        """Inserta batch en lml_listbuilder.privileges."""
        cursor.executemany("""
            INSERT INTO lml_listbuilder.privileges (
                listbuilder_id, privilege_id, privilege_name, privilege_code
            ) VALUES (%s, %s, %s, %s)
        """, records)