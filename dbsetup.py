r"""
Script de configuración inicial de la base de datos PostgreSQL.

Este script crea la estructura completa de schemas y tablas para el sistema
de migración MongoDB → PostgreSQL. Debe ejecutarse UNA SOLA VEZ antes de
iniciar las migraciones de datos.

Arquitectura:
- Schema 'public': Tablas compartidas (users, customers, areas, etc.)
- Schemas específicos: Un schema por colección (lml_processes, lml_listbuilder, etc.)

Características:
- Idempotente: Usa CREATE IF NOT EXISTS, puede ejecutarse múltiples veces
- Preserva datos: No usa DROP TABLE, los datos de migraciones previas se mantienen
- Respeta FKs: Las tablas se crean en orden de dependencias

Uso:
    python db_setup.py
    
    # Verificar schemas creados
    psql -U usuario -d mesamongo -c "\dn"
    
    # Verificar tablas
    psql -U usuario -d mesamongo -c "\dt public.*"
    psql -U usuario -d mesamongo -c "\dt lml_processes.*"
"""

import sys
import psycopg2
from psycopg2 import OperationalError, ProgrammingError
import config


def connect_to_postgres():
    """
    Establece conexión a PostgreSQL usando credenciales de config.py.
    
    Returns:
        tuple: (conexión, cursor) de psycopg2
        
    Raises:
        OperationalError: Si falla la conexión (credenciales, red, etc.)
        SystemExit: Termina el programa si no puede conectar
    """
    try:
        print("🔌 Conectando a PostgreSQL...")
        conn = psycopg2.connect(**config.POSTGRES_CONFIG)
        cursor = conn.cursor()
        print("✅ Conexión exitosa")
        return conn, cursor
    except OperationalError as e:
        print(f"❌ Error de conexión a PostgreSQL", file=sys.stderr)
        print(f"   Detalle: {e}", file=sys.stderr)
        sys.exit(1)


def setup_shared_tables(cursor, conn):
    """
    Crea las tablas compartidas en el schema 'public'.
    """
    print("\n🔧 Configurando tablas compartidas en schema 'public'...")
    
    tables = config.TABLE_NAMES
    
    try:
        # --- Nivel 1: Tablas sin dependencias ---
        
        # Customers
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS public.{tables['customers']} (
                id VARCHAR(255) PRIMARY KEY
            );
        """)
        
        # Areas
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS public.{tables['areas']} (
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255)
            );
        """)
        
        # Subareas
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS public.{tables['subareas']} (
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255)
            );
        """)
        
        # Roles
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS public.{tables['roles']} (
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255)
            );
        """)
        
        # Groups
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS public.{tables['groups']} (
                id VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255)
            );
        """)
        
        # --- Nivel 2: Users (con FKs a areas, subareas, roles) ---
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS public.{tables['users']} (
                id VARCHAR(255) PRIMARY KEY,
                email VARCHAR(255),
                firstname VARCHAR(255),
                lastname VARCHAR(255),
                area_id VARCHAR(255) REFERENCES public.{tables['areas']}(id),
                subarea_id VARCHAR(255) REFERENCES public.{tables['subareas']}(id),
                role_id VARCHAR(255) REFERENCES public.{tables['roles']}(id)
            );
        """)
        
        # --- Nivel 3: User Groups (tabla de relación N:M) ---
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS public.{tables['user_groups']} (
                user_id VARCHAR(255) REFERENCES public.{tables['users']}(id),
                group_id VARCHAR(255) REFERENCES public.{tables['groups']}(id),
                PRIMARY KEY (user_id, group_id)
            );
        """)
        
        conn.commit()
        print("✅ Tablas compartidas configuradas (7 tablas)")
        
    except Exception as e:
        print(f"❌ Error al configurar tablas compartidas: {e}")
        conn.rollback()
        raise e


def setup_lml_processes_schema(cursor, conn):
    """
    Crea el schema 'lml_processes' y sus tablas específicas.
    
    Este schema contiene los datos migrados de la colección MongoDB
    'lml_processes_mesa4core'. Las tablas se crean en orden respetando
    las Foreign Keys:
    
    1. Schema y tabla main (depende de public.customers y public.users)
    2. Tablas relacionadas (dependen de main.process_id)
    
    Args:
        cursor: Cursor de psycopg2 para ejecutar queries
        conn: Conexión de psycopg2 para commit/rollback
        
    Raises:
        ProgrammingError: Si hay error de SQL
        
    Note:
        Esta función asume que setup_shared_tables() ya fue ejecutada.
    """
    print("\n🔧 Configurando schema 'lml_processes'...")
    
    schema = "lml_processes"
    
    try:
        # Crear el schema
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
        
        # --- Tabla principal (nivel 4) ---
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.main (
                process_id VARCHAR(255) PRIMARY KEY,
                process_number VARCHAR(255),
                process_type_name VARCHAR(255),
                process_address TEXT,
                process_type_id VARCHAR(255),
                customer_id VARCHAR(255) REFERENCES public.customers(id),
                deleted BOOLEAN,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                process_date TIMESTAMP,
                lumbre_status_name VARCHAR(255),
                starter_id VARCHAR(255),
                starter_name VARCHAR(255),
                starter_type VARCHAR(50),
                created_by_user_id VARCHAR(255) REFERENCES public.users(id),
                updated_by_user_id VARCHAR(255) REFERENCES public.users(id)
            );
        """)
        
        # --- Tablas relacionadas (nivel 5) ---
        
        # Initiator fields
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.initiator_fields (
                id SERIAL PRIMARY KEY,
                process_id VARCHAR(255) REFERENCES {schema}.main(process_id),
                field_key VARCHAR(255),
                field_id VARCHAR(255),
                field_name VARCHAR(255)
            );
        """)
        
        # Process documents
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.process_documents (
                id SERIAL PRIMARY KEY,
                process_id VARCHAR(255) REFERENCES {schema}.main(process_id),
                doc_type VARCHAR(50),
                document_id VARCHAR(255)
            );
        """)
        
        # Last movements (relación 1:1 con main)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.last_movements (
                id SERIAL PRIMARY KEY,
                process_id VARCHAR(255) REFERENCES {schema}.main(process_id) UNIQUE,
                origin_user_id VARCHAR(255),
                origin_user_name VARCHAR(255),
                destination_user_id VARCHAR(255),
                destination_user_name VARCHAR(255),
                destination_area_name VARCHAR(255),
                destination_subarea_name VARCHAR(255)
            );
        """)
        
        # Movements (historial completo)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.movements (
                id SERIAL PRIMARY KEY,
                process_id VARCHAR(255) REFERENCES {schema}.main(process_id),
                movement_at TIMESTAMP,
                destination_id VARCHAR(255),
                destination_type VARCHAR(50)
            );
        """)
        
        conn.commit()
        print(f"✅ Schema '{schema}' configurado (5 tablas)")
        
    except Exception as e:
        print(f"❌ Error al configurar schema {schema}: {e}")
        conn.rollback()
        raise e 


def setup_lml_listbuilder_schema(cursor, conn):
    """
    Configura el schema lml_listbuilder para almacenar configuraciones de UI.
    """
    print("\n🔧 Configurando schema 'lml_listbuilder'...")
    
    schema = "lml_listbuilder"  # ← NUEVO
    tables = config.TABLE_NAMES
    
    try:  # ← NUEVO
        # Schema
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
        
        # Tabla principal
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.main ( 
                listbuilder_id VARCHAR(255) PRIMARY KEY,
                
                -- Identificadores de la configuración
                alias VARCHAR(500),
                title_list VARCHAR(500),
                gql_field VARCHAR(255),
                
                -- Query GraphQL
                gql_query TEXT,
                gql_variables JSONB,
                
                -- Configuración de visualización
                mode_table BOOLEAN DEFAULT true,
                mode_map BOOLEAN DEFAULT false,
                
                -- Metadata
                lumbre_internal BOOLEAN DEFAULT false,
                lumbre_version INTEGER,
                selectable BOOLEAN,
                items_per_page INTEGER,
                page INTEGER,
                
                -- Permisos (JSONB porque estructura variable)
                soft_permissions JSONB,
                aggs JSONB,
                meta_search JSONB,
                mode_box_options JSONB,
                
                -- Auditoría
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                created_by_user_id VARCHAR(255) REFERENCES public.{tables['users']}(id),
                updated_by_user_id VARCHAR(255) REFERENCES public.{tables['users']}(id),
                
                -- Relación con customer
                customer_id VARCHAR(255) REFERENCES public.{tables['customers']}(id),
                
                -- Metadata de MongoDB
                mongo_version INTEGER
            );
        """)
        
        # Índices en main
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_listbuilder_gql_field 
            ON {schema}.main(gql_field);
            
            CREATE INDEX IF NOT EXISTS idx_listbuilder_customer 
            ON {schema}.main(customer_id);
            
            CREATE INDEX IF NOT EXISTS idx_listbuilder_alias 
            ON {schema}.main(alias);
        """)
        
        # Tabla: fields (columnas visibles en la tabla)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.fields (
                id SERIAL PRIMARY KEY,
                listbuilder_id VARCHAR(255) REFERENCES {schema}.main(listbuilder_id) ON DELETE CASCADE,
                
                field_key VARCHAR(255),
                field_label VARCHAR(255),
                sortable BOOLEAN DEFAULT false,
                
                -- Orden de aparición
                field_order INTEGER,
                
                UNIQUE(listbuilder_id, field_key, field_order)
            );
        """)
        
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_fields_listbuilder 
            ON {schema}.fields(listbuilder_id);
        """)
        
        # Tabla: available_fields (todos los campos disponibles)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.available_fields (
                id SERIAL PRIMARY KEY,
                listbuilder_id VARCHAR(255) REFERENCES {schema}.main(listbuilder_id) ON DELETE CASCADE,
                
                field_key VARCHAR(255),
                field_label VARCHAR(255),
                sortable BOOLEAN DEFAULT false,
                
                field_order INTEGER,
                
                UNIQUE(listbuilder_id, field_key, field_order)
            );
        """)
        
        # Tabla: items (lista de items que se pueden mostrar)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.items (
                id SERIAL PRIMARY KEY,
                listbuilder_id VARCHAR(255) REFERENCES {schema}.main(listbuilder_id) ON DELETE CASCADE,
                
                item_name VARCHAR(255),
                item_order INTEGER,
                
                UNIQUE(listbuilder_id, item_name)
            );
        """)
        
        # Tabla: button_links (botones de acción)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.button_links (
                id SERIAL PRIMARY KEY,
                listbuilder_id VARCHAR(255) REFERENCES {schema}. main(listbuilder_id) ON DELETE CASCADE,
                
                button_value VARCHAR(255),
                button_to VARCHAR(500),
                button_class VARCHAR(100),
                endpoint_to_validate_visibility VARCHAR(500),
                show_button BOOLEAN DEFAULT true,
                disabled BOOLEAN DEFAULT false,
                
                button_order INTEGER
            );
        """)
        
        # Tabla: path_actions (acciones de navegación)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.path_actions (
                id SERIAL PRIMARY KEY,
                listbuilder_id VARCHAR(255) REFERENCES {schema}.main(listbuilder_id) ON DELETE CASCADE,
                
                action_to VARCHAR(500),
                tooltip VARCHAR(255),
                font_awesome_icon VARCHAR(100),
                
                action_order INTEGER
            );
        """)
        
        # Tabla: search_fields_selected
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.search_fields_selected (
                id SERIAL PRIMARY KEY,
                listbuilder_id VARCHAR(255) REFERENCES {schema}.main(listbuilder_id) ON DELETE CASCADE,
                
                field_name VARCHAR(255),
                field_order INTEGER,
                
                UNIQUE(listbuilder_id, field_name)
            );
        """)
        
        # Tabla: search_fields_to_selected
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.search_fields_to_selected (
                id SERIAL PRIMARY KEY,
                listbuilder_id VARCHAR(255) REFERENCES {schema}.main(listbuilder_id) ON DELETE CASCADE,
                
                field_name VARCHAR(255),
                field_order INTEGER,
                
                UNIQUE(listbuilder_id, field_name)
            );
        """)
        
        # Tabla: privileges (privilegios requeridos para acceder)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.privileges (
                id SERIAL PRIMARY KEY,
                listbuilder_id VARCHAR(255) REFERENCES {schema}.main(listbuilder_id) ON DELETE CASCADE,
                
                privilege_id VARCHAR(255),
                privilege_name VARCHAR(255),
                privilege_code VARCHAR(100),
                
                UNIQUE(listbuilder_id, privilege_id)
            );
        """)
        
        conn.commit()
        print(f"   ✅ Schema '{schema}' configurado (9 tablas)")
        
    except Exception as e:
        print(f"❌ Error al configurar schema {schema}: {e}")
        conn.rollback()
        raise e


def setup_lml_formbuilder_schema(cursor, conn):
    """
    Configura el schema lml_formbuilder.
    Estilo consistente con listbuilder: CREATE IF NOT EXISTS.
    """
    print("\n🔧 Configurando schema 'lml_formbuilder'...")
    
    schema = "lml_formbuilder"
    
    try:
        # 1. Crear Schema (No destructivo)
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
        
        # 2. Tabla Main
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.main (
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
                
                lumbre_internal BOOLEAN,
                lumbre_version INTEGER,
                
                created TIMESTAMP,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                
                customer_id VARCHAR(255) REFERENCES public.customers(id),
                created_by_user_id VARCHAR(255) REFERENCES public.users(id),
                updated_by_user_id VARCHAR(255) REFERENCES public.users(id),
                
                mongo_version INTEGER
            );
        """)
        
        # 3. Elements
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema}.elements (
                id SERIAL PRIMARY KEY,
                formbuilder_id VARCHAR(255) REFERENCES {schema}.main(formbuilder_id) ON DELETE CASCADE,
                
                element_id NUMERIC,
                component_name VARCHAR(100),
                form_object_to_send_to_server_property VARCHAR(255),
                class_name VARCHAR(100),
                
                component_props JSONB,
                component_permissions JSONB,
                visibility_depend_on_conditions JSONB,
                actions JSONB,
                validations JSONB,
                
                is_hidden_on_pdf BOOLEAN,
                has_label_on_pdf BOOLEAN,
                
                order_index INTEGER
            );
        """)

        # 4. Tablas de Permisos (usando tu loop - más elegante)
        for table_suffix in ['allow_access', 'allow_create', 'allow_update']:
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.{table_suffix} (
                    id SERIAL PRIMARY KEY,
                    formbuilder_id VARCHAR(255) REFERENCES {schema}.main(formbuilder_id) ON DELETE CASCADE,
                    privilege_id VARCHAR(255),
                    name VARCHAR(255),
                    codigo_privilegio VARCHAR(255)
                );
            """)
        
        conn.commit()
        print(f"✅ Schema '{schema}' verificado/creado correctamente.")
        
    except Exception as e:
        print(f"❌ Error al configurar schema {schema}: {e}")
        conn.rollback()
        raise e


def main():
    """
    Función principal que orquesta la creación de toda la estructura.
    
    Orden de ejecución:
    1. Conectar a PostgreSQL
    2. Crear tablas compartidas (public.*)
    3. Crear schemas específicos por colección
    4. Reportar éxito
    """
    print("🚀 Iniciando configuración de base de datos PostgreSQL...")
    print(f"   Base de datos: {config.POSTGRES_CONFIG['dbname']}")
    
    conn, cursor = connect_to_postgres()
    
    try:
        # Paso 1: Tablas compartidas
        setup_shared_tables(cursor, conn)
        
        # Paso 2: Schema lml_processes
        setup_lml_processes_schema(cursor, conn)
        
        # Paso 3: Schema lml_listbuilder
        setup_lml_listbuilder_schema(cursor, conn)

        # Paso 4: Schema lml_formbuilder
        setup_lml_formbuilder_schema(cursor, conn)


        print("\n" + "="*60)
        print("✅ SETUP COMPLETO")
        print("="*60)
        print("\nPróximos pasos:")
        print("  1. Verificar estructura: psql -U usuario -d mesamongo -c '\\dt public.*'")
        print("  2. Ejecutar migración: python mongomigra.py --collection lml_processes_mesa4core")
        
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}", file=sys.stderr)
        sys.exit(1)
        
    finally:
        cursor.close()
        conn.close()
        print("\n🔒 Conexión cerrada")


if __name__ == "__main__":
    main()