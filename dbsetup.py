# dbsetup.py
"""
Script de configuración de base de datos PostgreSQL. 
Crea todos los schemas y tablas necesarios para la migración desde MongoDB. 

ARQUITECTURA:
- lml_users: Schema para usuarios y sus catálogos (fuente de verdad)
- lml_usersgroups: Schema para grupos y relación N:M con usuarios
- lml_*: Schemas por colección MongoDB (solo FKs entre ellos)

CONVENCIÓN DE NAMING:
Colección MongoDB              Schema PostgreSQL
--------------------          -------------------
lml_users_mesa4core       →   lml_users
lml_usersgroups_mesa4core →   lml_usersgroups
lml_*_mesa4core           →   lml_*
"""

import psycopg2
from psycopg2 import sql
import config

def create_connection():
    """Establece conexión con PostgreSQL."""
    try:
        conn = psycopg2.connect(**config.POSTGRES_CONFIG)
        return conn
    except Exception as e:
        print(f"❌ Error conectando a PostgreSQL: {e}")
        return None

def setup_lml_users_schema(cursor):
    """
    Crea schema lml_users con tablas de usuarios y catálogos relacionados.
    
    FUENTE DE VERDAD: lml_users_mesa4core
    
    TABLAS:
    - main: Datos principales de usuarios
    - roles, areas, subareas, positions, signaturetypes: Catálogos embebidos
    
    DECISIONES DE DISEÑO:
    - password puede ser NULL (usuarios SSO/externos)
    - position_id y signaturetype_id son NULL (solo 5. 5% cobertura)
    - postgres_id descartado (campo legacy)
    - privileges NO migrados (no existen en nivel raíz de documentos)
    """
    print("\n   🔧 Creando schema 'lml_users'...")
    
    # Crear schema
    cursor.execute("CREATE SCHEMA IF NOT EXISTS lml_users")
    
    # Catálogo: Roles
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_users.roles (
            id VARCHAR(255) PRIMARY KEY,
            name VARCHAR(500) NOT NULL
        )
    """)
    
    # Catálogo: Áreas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_users.areas (
            id VARCHAR(255) PRIMARY KEY,
            name VARCHAR(500) NOT NULL,
            descripcion TEXT
        )
    """)
    
    # Catálogo: Subáreas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_users.subareas (
            id VARCHAR(255) PRIMARY KEY,
            name VARCHAR(500) NOT NULL
        )
    """)
    
    # Catálogo: Posiciones
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_users.positions (
            id VARCHAR(255) PRIMARY KEY,
            name VARCHAR(500) NOT NULL
        )
    """)
    
    # Catálogo: Tipos de Firma
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_users.signaturetypes (
            id VARCHAR(255) PRIMARY KEY,
            name VARCHAR(500) NOT NULL,
            descripcion TEXT
        )
    """)
    
    # Tabla principal: Usuarios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_users.main (
            id VARCHAR(255) PRIMARY KEY,
            firstname VARCHAR(255) NOT NULL,
            lastname VARCHAR(255) NOT NULL,
            username VARCHAR(255),
            email VARCHAR(255) NOT NULL,
            password VARCHAR(500),
            
            -- FKs a catálogos
            role_id VARCHAR(255) REFERENCES lml_users.roles(id),
            area_id VARCHAR(255) REFERENCES lml_users.areas(id),
            subarea_id VARCHAR(255) REFERENCES lml_users.subareas(id),
            position_id VARCHAR(255) REFERENCES lml_users.positions(id),
            signaturetype_id VARCHAR(255) REFERENCES lml_users.signaturetypes(id),
            
            -- Relación externa
            customer_id VARCHAR(255),
            
            -- Metadata
            deleted BOOLEAN DEFAULT FALSE,
            user_type VARCHAR(50),
            license_status VARCHAR(50),
            signature TEXT,
            dni VARCHAR(50),
            lumbre_version INTEGER,
            
            -- Timestamps
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            
            -- Auditoría
            updated_by_user_id VARCHAR(255),
            
            -- Mongoose metadata
            __v INTEGER
        )
    """)
    
    print("   ✅ Schema 'lml_users' creado (6 tablas)")

def setup_lml_usersgroups_schema(cursor):
    """
    Crea schema lml_usersgroups con grupos y relación N:M con usuarios.
    
    FUENTE DE VERDAD: lml_usersgroups_mesa4core
    
    TABLAS:
    - main: Catálogo de grupos
    - members: Relación N:M (group_id, user_id)
    
    DECISIONES DE DISEÑO:
    - members usa ON DELETE CASCADE
    - Índice en members(user_id) para query "grupos de un usuario"
    - pases NO migrado (43. 5% cobertura, propósito poco claro)
    """
    print("\n   🔧 Creando schema 'lml_usersgroups'...")
    
    # Crear schema
    cursor.execute("CREATE SCHEMA IF NOT EXISTS lml_usersgroups")
    
    # Tabla principal: Grupos
    cursor. execute("""
        CREATE TABLE IF NOT EXISTS lml_usersgroups.main (
            id VARCHAR(255) PRIMARY KEY,
            name VARCHAR(500) NOT NULL,
            alias VARCHAR(500) NOT NULL,
            deleted BOOLEAN DEFAULT FALSE,
            customer_id VARCHAR(255),
            lumbre_version INTEGER DEFAULT 1,
            imported_from_external BOOLEAN,
            
            -- Timestamps
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            
            -- Auditoría
            created_by_user_id VARCHAR(255),
            updated_by_user_id VARCHAR(255),
            
            -- Mongoose metadata
            __v INTEGER
        )
    """)
    
    # Tabla N:M: Membresías
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_usersgroups. members (
            group_id VARCHAR(255) REFERENCES lml_usersgroups.main(id) ON DELETE CASCADE,
            user_id VARCHAR(255) REFERENCES lml_users.main(id) ON DELETE CASCADE,
            PRIMARY KEY (group_id, user_id)
        )
    """)
    
    # Índice para query inversa
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_members_user_id 
        ON lml_usersgroups.members(user_id)
    """)
    
    print("   ✅ Schema 'lml_usersgroups' creado (2 tablas + 1 índice)")

def setup_lml_formbuilder_schema(cursor):
    """
    Crea schema lml_formbuilder. 
    
    ESTRUCTURA ORIGINAL RESTAURADA:
    - main: Configuración del formulario
    - elements: Componentes del formulario (inputs, buttons, etc.)
    - allow_access, allow_create, allow_update: Permisos por operación
    
    DIFERENCIA CON PROCESOS/LISTBUILDER:
    - NO usa tablas *_area, *_role, *_user, *_group
    - Usa tablas por TIPO DE OPERACIÓN (access/create/update)
    - Cada tabla almacena privilege objects {id, name, codigo}
    """
    print("\n   🔧 Creando schema 'lml_formbuilder'...")
    
    cursor.execute("CREATE SCHEMA IF NOT EXISTS lml_formbuilder")
    
    # Tabla principal
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_formbuilder.main (
            formbuilder_id VARCHAR(255) PRIMARY KEY,
            alias VARCHAR(500),
            page_title_data VARCHAR(500),
            message_after_post_or_put TEXT,
            path_to_redirect_after_post_or_put TEXT,
            api_rest_for_handle_all_http_methods TEXT,
            
            -- Campos JSONB (estructura variable)
            validations JSONB,
            conditionals JSONB,
            soft_permissions JSONB,
            
            -- Metadata
            lumbre_internal BOOLEAN,
            lumbre_version INTEGER,
            mongo_version INTEGER,
            
            -- Timestamps (notar inconsistencia: 'created' y 'created_at')
            created TIMESTAMP,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            
            -- FKs actualizadas
            customer_id VARCHAR(255),
            created_by_user_id VARCHAR(255) REFERENCES lml_users. main(id),
            updated_by_user_id VARCHAR(255) REFERENCES lml_users.main(id)
        )
    """)
    
    # Tabla: elements (componentes del formulario)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_formbuilder.elements (
            id SERIAL PRIMARY KEY,
            formbuilder_id VARCHAR(255) REFERENCES lml_formbuilder.main(formbuilder_id) ON DELETE CASCADE,
            
            element_id NUMERIC,
            component_name VARCHAR(100),
            form_object_to_send_to_server_property VARCHAR(255),
            class_name VARCHAR(100),
            
            -- Configuración compleja en JSONB
            component_props JSONB,
            component_permissions JSONB,
            visibility_depend_on_conditions JSONB,
            actions JSONB,
            validations JSONB,
            
            -- PDF rendering
            is_hidden_on_pdf BOOLEAN,
            has_label_on_pdf BOOLEAN,
            
            -- Orden visual
            order_index INTEGER
        )
    """)
    
    # Tablas de permisos por tipo de operación
    for table_suffix in ['allow_access', 'allow_create', 'allow_update']:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS lml_formbuilder. {table_suffix} (
                id SERIAL PRIMARY KEY,
                formbuilder_id VARCHAR(255) REFERENCES lml_formbuilder.main(formbuilder_id) ON DELETE CASCADE,
                
                privilege_id VARCHAR(255),
                name VARCHAR(255),
                codigo_privilegio VARCHAR(255),
                
                -- Evitar duplicados
                UNIQUE(formbuilder_id, privilege_id)
            )
        """)
    
    print("   ✅ Schema 'lml_formbuilder' creado (5 tablas y 8 índices)")

def setup_lml_listbuilder_schema(cursor):
    """
    Crea schema lml_listbuilder.
    
    ESTRUCTURA ORIGINAL COMPLETA:
    - main: Configuración del listado (query GraphQL, permisos, etc.)
    - fields/available_fields: Columnas visibles y disponibles
    - items: Elementos que se pueden mostrar
    - button_links/path_actions: Botones y acciones de UI
    - search_fields_*: Configuración de búsqueda
    - privileges: Permisos requeridos para acceder
    
    COMPLEJIDAD:
    - 9 tablas (más complejo que formbuilder)
    - Almacena configuración completa de UI (no solo permisos)
    - 3 índices en tabla main para queries frecuentes
    """
    print("\n   🔧 Creando schema 'lml_listbuilder'...")
    
    cursor.execute("CREATE SCHEMA IF NOT EXISTS lml_listbuilder")
    
    # Tabla principal
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_listbuilder.main (
            listbuilder_id VARCHAR(255) PRIMARY KEY,
            
            -- Identificación
            alias VARCHAR(500),
            title_list VARCHAR(500),
            gql_field VARCHAR(255),
            
            -- Query GraphQL
            gql_query TEXT,
            gql_variables JSONB,
            
            -- Modos de visualización
            mode_table BOOLEAN DEFAULT TRUE,
            mode_map BOOLEAN DEFAULT FALSE,
            
            -- Metadata
            lumbre_internal BOOLEAN DEFAULT FALSE,
            lumbre_version INTEGER,
            mongo_version INTEGER,
            selectable BOOLEAN,
            items_per_page INTEGER,
            page INTEGER,
            
            -- Configuraciones complejas (JSONB)
            soft_permissions JSONB,
            aggs JSONB,
            meta_search JSONB,
            mode_box_options JSONB,
            
            -- Timestamps
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            
            -- FKs actualizadas
            customer_id VARCHAR(255),
            created_by_user_id VARCHAR(255) REFERENCES lml_users.main(id),
            updated_by_user_id VARCHAR(255) REFERENCES lml_users.main(id)
        )
    """)
    
    # Índices estratégicos
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_listbuilder_gql_field 
        ON lml_listbuilder.main(gql_field);
        
        CREATE INDEX IF NOT EXISTS idx_listbuilder_customer 
        ON lml_listbuilder.main(customer_id);
        
        CREATE INDEX IF NOT EXISTS idx_listbuilder_alias 
        ON lml_listbuilder.main(alias);
    """)
    
    # Tabla: fields (columnas visibles)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_listbuilder.fields (
            id SERIAL PRIMARY KEY,
            listbuilder_id VARCHAR(255) REFERENCES lml_listbuilder.main(listbuilder_id) ON DELETE CASCADE,
            
            field_key VARCHAR(255),
            field_label VARCHAR(255),
            sortable BOOLEAN DEFAULT FALSE,
            field_order INTEGER,
            
            UNIQUE(listbuilder_id, field_key, field_order)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_fields_listbuilder 
        ON lml_listbuilder.fields(listbuilder_id);
    """)
    
    # Tabla: available_fields (todos los campos disponibles)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_listbuilder.available_fields (
            id SERIAL PRIMARY KEY,
            listbuilder_id VARCHAR(255) REFERENCES lml_listbuilder.main(listbuilder_id) ON DELETE CASCADE,
            
            field_key VARCHAR(255),
            field_label VARCHAR(255),
            sortable BOOLEAN DEFAULT FALSE,
            field_order INTEGER,
            
            UNIQUE(listbuilder_id, field_key, field_order)
        )
    """)
    
    # Tabla: items
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_listbuilder.items (
            id SERIAL PRIMARY KEY,
            listbuilder_id VARCHAR(255) REFERENCES lml_listbuilder.main(listbuilder_id) ON DELETE CASCADE,
            
            item_name VARCHAR(255),
            item_order INTEGER,
            
            UNIQUE(listbuilder_id, item_name)
        )
    """)
    
    # Tabla: button_links (botones de acción)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_listbuilder.button_links (
            id SERIAL PRIMARY KEY,
            listbuilder_id VARCHAR(255) REFERENCES lml_listbuilder.main(listbuilder_id) ON DELETE CASCADE,
            
            button_value VARCHAR(255),
            button_to VARCHAR(500),
            button_class VARCHAR(100),
            endpoint_to_validate_visibility VARCHAR(500),
            show_button BOOLEAN DEFAULT TRUE,
            disabled BOOLEAN DEFAULT FALSE,
            button_order INTEGER
        )
    """)
    
    # Tabla: path_actions (acciones de navegación)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_listbuilder.path_actions (
            id SERIAL PRIMARY KEY,
            listbuilder_id VARCHAR(255) REFERENCES lml_listbuilder.main(listbuilder_id) ON DELETE CASCADE,
            
            action_to VARCHAR(500),
            tooltip VARCHAR(255),
            font_awesome_icon VARCHAR(100),
            action_order INTEGER
        )
    """)
    
    # Tabla: search_fields_selected
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_listbuilder.search_fields_selected (
            id SERIAL PRIMARY KEY,
            listbuilder_id VARCHAR(255) REFERENCES lml_listbuilder.main(listbuilder_id) ON DELETE CASCADE,
            
            field_name VARCHAR(255),
            field_order INTEGER,
            
            UNIQUE(listbuilder_id, field_name)
        )
    """)
    
    # Tabla: search_fields_to_selected
    cursor. execute("""
        CREATE TABLE IF NOT EXISTS lml_listbuilder.search_fields_to_selected (
            id SERIAL PRIMARY KEY,
            listbuilder_id VARCHAR(255) REFERENCES lml_listbuilder.main(listbuilder_id) ON DELETE CASCADE,
            
            field_name VARCHAR(255),
            field_order INTEGER,
            
            UNIQUE(listbuilder_id, field_name)
        )
    """)
    
    # Tabla: privileges
    cursor. execute("""
        CREATE TABLE IF NOT EXISTS lml_listbuilder.privileges (
            id SERIAL PRIMARY KEY,
            listbuilder_id VARCHAR(255) REFERENCES lml_listbuilder.main(listbuilder_id) ON DELETE CASCADE,
            
            privilege_id VARCHAR(255),
            privilege_name VARCHAR(255),
            privilege_code VARCHAR(100),
            
            UNIQUE(listbuilder_id, privilege_id)
        )
    """)
    
    print("   ✅ Schema 'lml_listbuilder' creado (9 tablas + 19 índices)")

def setup_lml_processes_schema(cursor):
    """
    Crea schema lml_processes con estructura completa.
    
    TABLAS:
    - main: Datos principales del trámite
    - initiator_fields: Campos del iniciador (N:1)
    - process_documents: Documentos relacionados (N:M)
    - last_movements: Último movimiento (1:1)
    - movements: Historial de movimientos (N:1)
    
    DECISIONES DE DISEÑO:
    - FKs actualizadas a lml_users.main en vez de public.users
    - ON DELETE CASCADE en tablas relacionales para limpieza automática
    - last_movements usa UNIQUE(process_id) para garantizar relación 1:1
    """
    print("\n   🔧 Creando schema 'lml_processes'...")
    
    cursor.execute("CREATE SCHEMA IF NOT EXISTS lml_processes")
    
    # Tabla principal
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_processes.main (
            process_id VARCHAR(255) PRIMARY KEY,
            process_number VARCHAR(255),
            process_type_name VARCHAR(255),
            process_address TEXT,
            process_type_id VARCHAR(255),
            process_date TIMESTAMP,
            
            -- FKs actualizadas
            customer_id VARCHAR(255),
            created_by_user_id VARCHAR(255) REFERENCES lml_users.main(id),
            updated_by_user_id VARCHAR(255) REFERENCES lml_users.main(id),
            
            -- Metadata del iniciador (campos embebidos)
            starter_id VARCHAR(255),
            starter_name VARCHAR(255),
            starter_type VARCHAR(50),
            
            -- Estado del proceso
            lumbre_status_name VARCHAR(255),
            
            -- Metadata
            deleted BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    
    # Tabla: initiator_fields (campos del formulario del iniciador)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_processes.initiator_fields (
            id SERIAL PRIMARY KEY,
            process_id VARCHAR(255) REFERENCES lml_processes.main(process_id) ON DELETE CASCADE,
            
            field_key VARCHAR(255),
            field_id VARCHAR(255),
            field_name VARCHAR(255),
            
            -- Evitar duplicados
            UNIQUE(process_id, field_key)
        )
    """)
    
    # Tabla: process_documents (documentos asociados al trámite)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_processes.process_documents (
            id SERIAL PRIMARY KEY,
            process_id VARCHAR(255) REFERENCES lml_processes.main(process_id) ON DELETE CASCADE,
            
            doc_type VARCHAR(50),
            document_id VARCHAR(255),
            
            -- Un documento puede estar en múltiples procesos
            UNIQUE(process_id, document_id)
        )
    """)
    
    # Tabla: last_movements (último movimiento, relación 1:1)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_processes.last_movements (
            id SERIAL PRIMARY KEY,
            process_id VARCHAR(255) REFERENCES lml_processes. main(process_id) ON DELETE CASCADE UNIQUE,
            
            -- Usuario origen (quien envió)
            origin_user_id VARCHAR(255),
            origin_user_name VARCHAR(255),
            
            -- Destino (usuario/área que recibió)
            destination_user_id VARCHAR(255),
            destination_user_name VARCHAR(255),
            destination_area_name VARCHAR(255),
            destination_subarea_name VARCHAR(255)
        )
    """)
    
    # Tabla: movements (historial completo de movimientos)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_processes. movements (
            id SERIAL PRIMARY KEY,
            process_id VARCHAR(255) REFERENCES lml_processes.main(process_id) ON DELETE CASCADE,
            
            movement_at TIMESTAMP,
            destination_id VARCHAR(255),
            destination_type VARCHAR(50)
        )
    """)
    
    # Índices para queries frecuentes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_processes_customer 
        ON lml_processes.main(customer_id);
        
        CREATE INDEX IF NOT EXISTS idx_processes_created_by 
        ON lml_processes. main(created_by_user_id);
        
        CREATE INDEX IF NOT EXISTS idx_movements_process 
        ON lml_processes. movements(process_id);
    """)
    
    print("   ✅ Schema 'lml_processes' creado (5 tablas + 11 índices)")

def main():
    """
    Punto de entrada principal. 
    
    ORDEN DE EJECUCIÓN:
    1. lml_users (sin dependencias)
    2. lml_usersgroups (depende de lml_users. main)
    3.  Resto (dependen de lml_users.* y lml_usersgroups. *)
    """
    print("=" * 80)
    print("🚀 CONFIGURACIÓN DE BASE DE DATOS PostgreSQL")
    print("=" * 80)
    
    conn = create_connection()
    if not conn:
        print("\n❌ No se pudo conectar a la base de datos")
        return
    
    cursor = conn.cursor()
    
    try:
        print("\n🔨 Creando estructura de base de datos...")
        
        # Orden crítico: fuentes de verdad primero
        setup_lml_users_schema(cursor)
        setup_lml_usersgroups_schema(cursor)
        setup_lml_processes_schema(cursor)
        setup_lml_listbuilder_schema(cursor)
        setup_lml_formbuilder_schema(cursor)
        
        conn.commit()
        
        print("\n" + "=" * 80)
        print("✅ Base de datos configurada correctamente")
        print("=" * 80)
        
        # Resumen
        print("\n📊 ESQUEMAS CREADOS:")
        print("  - lml_users: 6 tablas (1 main + 5 catálogos)")
        print("  - lml_usersgroups: 2 tablas (1 main + 1 relación N:M)")
        print("  - lml_processes: 5 tablas y 11 índices")
        print("  - lml_listbuilder: 9 tablas y 19 índices")
        print("  - lml_formbuilder: 5 tablas y 8 índices")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error durante la configuración: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    main()