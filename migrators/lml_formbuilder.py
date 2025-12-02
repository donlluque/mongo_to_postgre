"""
Migrador para la colección lml_formbuilder_mesa4core. 

Implementa la interfaz BaseMigrator para transformar configuraciones de formularios
dinámicos desde MongoDB al schema PostgreSQL 'lml_formbuilder'. 

Características:
- Volumen: ~200 configuraciones de formularios
- Complejidad: formElements[] con avg 8.5 elementos, estructura profundamente anidada
- Arrays normalizados: formElements → tabla, privilegios → 3 tablas separadas
- JSONB: validations (55 estructuras), conditionals, soft_permissions

Tablas destino:
- {schema}. main: Configuración principal del formulario
- {schema}.elements: Elementos del formulario (campos, botones, etc.) - 1:N
- {schema}.allow_access: Privilegios de acceso - 1:N
- {schema}.allow_create: Privilegios de creación - 1:N
- {schema}.allow_update: Privilegios de actualización - 1:N
"""

import json
from datetime import datetime
from .base import BaseMigrator


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


    # =========================================================================
    # MÉTODOS PÚBLICOS - INTERFAZ REQUERIDA (Métodos Simples)
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
        - main: Tuplas para lml_formbuilder. main
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
        """.. ."""
        result = {
            'customer_id': None,
            'created_by_user_id': None,
            'updated_by_user_id': None
        }
        
        # === 1. Customer ID ===
        customer_id = doc.get('customerId')
        if customer_id and customer_id not in caches['customers']:
            try:
                cursor.execute(
                    "INSERT INTO public.customers (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                    (customer_id,)
                )
                caches['customers'].add(customer_id)
            except Exception as e:  # ← Capturar error original
                print(f"\n❌ ERROR EN INSERT CUSTOMER: {e}")
                print(f"   Customer ID: {customer_id}")
                print(f"   Doc _id: {doc.get('_id')}")
                raise  # Re-lanzar para abortar migración
        
        result['customer_id'] = customer_id
        
        # === 2. CreatedBy user ===
        created_by = doc.get('createdBy', {})
        if created_by:
            user_id = self._extract_user_id_from_action(created_by)
            if user_id:
                try:
                    self._insert_user_if_needed(created_by. get('user', {}), cursor, caches)
                    result['created_by_user_id'] = str(user_id)
                except Exception as e:  # ← Capturar error original
                    print(f"\n❌ ERROR EN INSERT CREATED_BY USER: {e}")
                    print(f"   User ID: {user_id}")
                    print(f"   Doc _id: {doc.get('_id')}")
                    raise
        
        # === 3. UpdatedBy user ===
        updated_by = doc.get('updatedBy', {})
        if updated_by:
            user_id = self._extract_user_id_from_action(updated_by)
            if user_id:
                try:
                    self._insert_user_if_needed(updated_by.get('user', {}), cursor, caches)
                    result['updated_by_user_id'] = str(user_id)
                except Exception as e:  # ← Capturar error original
                    print(f"\n❌ ERROR EN INSERT UPDATED_BY USER: {e}")
                    print(f"   User ID: {user_id}")
                    print(f"   Doc _id: {doc.get('_id')}")
                    raise
        
        return result


    # =========================================================================
    # MÉTODOS PRIVADOS - PROCESAMIENTO DE USUARIOS
    # =========================================================================
    
    def _extract_user_id_from_action(self, action_obj):
        """
        Extrae el ID de usuario de un objeto createdBy/updatedBy.
        
        La estructura puede variar:
        - user puede ser un string (ID directo)
        - user puede ser un objeto con 'id' o '_id'
        
        Args:
            action_obj: Dict con estructura {user: .. ., userAgent: .. ., ...}
            
        Returns:
            str | None: ID del usuario o None si no se encuentra
        """
        if not action_obj or not isinstance(action_obj, dict):
            return None
        
        user = action_obj. get('user', {})
        
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
                    return mongo_id. get('$oid')
                return mongo_id
        
        return None
    
    def _insert_user_if_needed(self, user_obj, cursor, caches):
        """
        Inserta un usuario en public.users si no existe.
        
        Maneja estructura completa con relaciones (area, subarea, role, groups). 
        Inserta entidades relacionadas en orden de dependencias.
        
        Args:
            user_obj: Dict con datos completos del usuario
            cursor: Cursor de psycopg2
            caches: Dict de sets para tracking de inserts
        """
        if not user_obj or not isinstance(user_obj, dict):
            return
        
        user_id = user_obj. get('id')
        if not user_id or user_id in caches['users']:
            return
        
        # === Extraer relaciones ===
        area = user_obj.get('area', {})
        area_id = area.get('id') if isinstance(area, dict) else None
        
        subarea = user_obj. get('subarea', {})
        subarea_id = subarea.get('id') if isinstance(subarea, dict) else None
        
        role = user_obj.get('role', {})
        role_id = role.get('id') if isinstance(role, dict) else None
        
        # === Insertar entidades relacionadas (orden de dependencias) ===
        
        # 1. Areas (sin dependencias)
        if area_id and area_id not in caches['areas']:
            cursor. execute(
                "INSERT INTO public.areas (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (area_id, area. get('name'))
            )
            caches['areas'].add(area_id)
        
        # 2. Subareas (sin dependencias)
        if subarea_id and subarea_id not in caches['subareas']:
            cursor.execute(
                "INSERT INTO public.subareas (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (subarea_id, subarea.get('name'))
            )
            caches['subareas'].add(subarea_id)
        
        # 3. Roles (sin dependencias)
        if role_id and role_id not in caches['roles']:
            cursor.execute(
                "INSERT INTO public. roles (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (role_id, role.get('name'))
            )
            caches['roles'].add(role_id)
        
        # === Insertar usuario (depende de area, subarea, role) ===
        cursor.execute("""
            INSERT INTO public.users (id, email, firstname, lastname, area_id, subarea_id, role_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            str(user_id),
            user_obj.get('email'),
            user_obj.get('firstname'),
            user_obj. get('lastname'),
            area_id,
            subarea_id,
            role_id
        ))
        
        caches['users'].add(user_id)
        
        # === Insertar grupos (relación N:M) ===
        groups = user_obj.get('groups', [])
        for group in groups:
            if not isinstance(group, dict):
                continue
            
            group_id = group.get('id')
            if not group_id:
                continue
            
            # Insertar grupo si no existe
            if group_id not in caches['groups']:
                cursor.execute(
                    "INSERT INTO public.groups (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (group_id, group.get('name'))
                )
                caches['groups'].add(group_id)
            
            # Insertar relación user-group (no necesita cache - PK compuesta evita duplicados)
            cursor. execute(
                "INSERT INTO public.user_groups (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (str(user_id), group_id)
            )

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
        formbuilder_id = self. get_primary_key_from_doc(doc)
        
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
        - Campos JSONB (dicts/arrays → json. dumps)
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

    def _parse_mongo_date(self, date_value):
        """
        Parsea fechas de MongoDB en múltiples formatos.
        
        MongoDB exporta fechas en al menos 3 formatos:
        1. Extended JSON: {"$date": "2021-03-04T17:34:21.974Z"}
        2. String ISO8601: "2021-03-04T17:34:21. 974Z"
        3. String ISO8601 sin milisegundos: "2021-03-04T17:34:21Z"
        
        Args:
            date_value: Valor del campo fecha (dict, string, o None)
            
        Returns:
            datetime | None: Fecha parseada o None si no es válida
        """
        if not date_value:
            return None
        
        # Caso 1: Extended JSON
        if isinstance(date_value, dict) and '$date' in date_value:
            date_value = date_value['$date']
        
        # Caso 2 y 3: String ISO8601
        if isinstance(date_value, str):
            try:
                # Con milisegundos
                if '.' in date_value:
                    return datetime.strptime(date_value, "%Y-%m-%dT%H:%M:%S.%fZ")
                # Sin milisegundos
                else:
                    return datetime.strptime(date_value, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
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
            validations = elem. get('validations')
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
                priv. get('id'),
                priv.get('name'),
                priv.get('codigo_privilegio')
            ))
        
        return records

    # =========================================================================
    # MÉTODOS PÚBLICOS - INSERCIÓN DE BATCHES
    # =========================================================================
    
    def insert_batches(self, batches, cursor):
        """
        Inserta todos los batches acumulados en PostgreSQL.
        
        Implementa interfaz de BaseMigrator. 
        
        Ejecuta inserts en orden de dependencias:
        1. main (parent)
        2. elements, allow_access, allow_create, allow_update (children con FK a main)
        
        Args:
            batches: Dict con estructura {
                'main': [tuplas],
                'related': {
                    'elements': [tuplas],
                    'allow_access': [tuplas],
                    'allow_create': [tuplas],
                    'allow_update': [tuplas]
                }
            }
            cursor: Cursor de psycopg2
        """
        # 1. Insertar tabla main (debe ir primero por FKs)
        if batches['main']:
            self._insert_main_batch(batches['main'], cursor)
        
        # 2.  Insertar tablas relacionadas (orden no importa entre ellas, solo después de main)
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
            INSERT INTO {self. schema}.allow_access (
                formbuilder_id,
                privilege_id,
                name,
                codigo_privilegio
            ) VALUES (%s, %s, %s, %s)
        """, records)
    
    def _insert_allow_create_batch(self, records, cursor):
        """Inserta batch en lml_formbuilder.allow_create."""
        cursor.executemany(f"""
            INSERT INTO {self.schema}. allow_create (
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

