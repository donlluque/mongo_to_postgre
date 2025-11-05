import sys
import psycopg2
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from psycopg2 import OperationalError, ProgrammingError
import json  # Asegurarse de tener import json aunque no se use directamente aquí.

# Configuración centralizada
import config

def connect_to_mongo():
    """Crea y retorna una conexión a la base de datos MongoDB."""
    try:
        print("🔌 Conectando a MongoDB...")
        client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping') 
        db = client[config.MONGO_DATABASE_NAME]
        print("✅ Conexión a MongoDB exitosa.")
        return db
    except ConnectionFailure as e:
        print(f"❌ Error: No se pudo conectar a MongoDB.", file=sys.stderr)
        print(f"Detalle: {e}", file=sys.stderr)
        sys.exit(1)

def connect_to_postgres():
    """Crea y retorna una conexión y un cursor a la base de datos PostgreSQL."""
    try:
        print("🔌 Conectando a PostgreSQL...")
        conn = psycopg2.connect(**config.POSTGRES_CONFIG)
        cursor = conn.cursor()
        print("✅ Conexión a PostgreSQL exitosa.")
        return conn, cursor
    except OperationalError as e:
        print(f"❌ Error: No se pudo conectar a PostgreSQL.", file=sys.stderr)
        print(f"Detalle: {e}", file=sys.stderr)
        sys.exit(1)


# Reemplaza tu función create_postgres_tables con esta:

def create_postgres_tables(pg_cursor, pg_conn):
    """
    Crea las tablas de destino con la nueva nomenclatura y la tabla de clientes.
    """
    try:
        print("\n🔧 Creando esquema híbrido actualizado en PostgreSQL...")
        
        schema = config.POC_SCHEMA_NAME
        tables = config.TABLE_NAMES

        pg_cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")

        # --- Tablas Compartidas en 'public' ---
        print("   -> Creando tablas compartidas en schema 'public'...")
        
        pg_cursor.execute(f"DROP TABLE IF EXISTS public.{tables['customers']} CASCADE;")
        pg_cursor.execute(f"CREATE TABLE public.{tables['customers']} (id VARCHAR(255) PRIMARY KEY);")

        pg_cursor.execute(f"DROP TABLE IF EXISTS public.{tables['areas']} CASCADE;")
        pg_cursor.execute(f"CREATE TABLE public.{tables['areas']} (id VARCHAR(255) PRIMARY KEY, name VARCHAR(255));")

        pg_cursor.execute(f"DROP TABLE IF EXISTS public.{tables['subareas']} CASCADE;")
        pg_cursor.execute(f"CREATE TABLE public.{tables['subareas']} (id VARCHAR(255) PRIMARY KEY, name VARCHAR(255));")
        
        pg_cursor.execute(f"DROP TABLE IF EXISTS public.{tables['roles']} CASCADE;")
        pg_cursor.execute(f"CREATE TABLE public.{tables['roles']} (id VARCHAR(255) PRIMARY KEY, name VARCHAR(255));")
        
        pg_cursor.execute(f"DROP TABLE IF EXISTS public.{tables['groups']} CASCADE;")
        pg_cursor.execute(f"CREATE TABLE public.{tables['groups']} (id VARCHAR(255) PRIMARY KEY, name VARCHAR(255));")
        
        pg_cursor.execute(f"DROP TABLE IF EXISTS public.{tables['users']} CASCADE;")
        pg_cursor.execute(f"""
            CREATE TABLE public.{tables['users']} (
                id VARCHAR(255) PRIMARY KEY, email VARCHAR(255) UNIQUE, firstname VARCHAR(255),
                lastname VARCHAR(255), area_id VARCHAR(255) REFERENCES public.{tables['areas']}(id),
                subarea_id VARCHAR(255) REFERENCES public.{tables['subareas']}(id),
                role_id VARCHAR(255) REFERENCES public.{tables['roles']}(id)
            );
        """)

        pg_cursor.execute(f"DROP TABLE IF EXISTS public.{tables['user_groups']} CASCADE;")
        pg_cursor.execute(f"""
            CREATE TABLE public.{tables['user_groups']} (
                user_id VARCHAR(255) REFERENCES public.{tables['users']}(id),
                group_id VARCHAR(255) REFERENCES public.{tables['groups']}(id),
                PRIMARY KEY (user_id, group_id)
            );
        """)


        # --- Tablas Específicas en su propio schema ---
        print(f"   -> Creando tablas específicas en schema '{schema}'...")
        pg_cursor.execute(f"DROP TABLE IF EXISTS {schema}.main CASCADE;")
        pg_cursor.execute(f"""
            CREATE TABLE {schema}.main (
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

        pg_cursor.execute(f"DROP TABLE IF EXISTS {schema}.initiator_fields CASCADE;")
        pg_cursor.execute(f"""
            CREATE TABLE {schema}.initiator_fields (
                id SERIAL PRIMARY KEY,
                process_id VARCHAR(255) REFERENCES {schema}.main(process_id),
                field_key VARCHAR(255),
                field_id VARCHAR(255),
                field_name VARCHAR(255)
            );
        """)

        pg_cursor.execute(f"DROP TABLE IF EXISTS {schema}.process_documents CASCADE;")
        pg_cursor.execute(f"""
            CREATE TABLE {schema}.process_documents (
                id SERIAL PRIMARY KEY,
                process_id VARCHAR(255) REFERENCES {schema}.main(process_id),
                doc_type VARCHAR(50),
                document_id VARCHAR(255)
            );
        """)

        pg_cursor.execute(f"DROP TABLE IF EXISTS {schema}.last_movements CASCADE;")
        pg_cursor.execute(f"""
            CREATE TABLE {schema}.last_movements (
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
        
        pg_cursor.execute(f"DROP TABLE IF EXISTS {schema}.movements CASCADE;")
        pg_cursor.execute(f"""
            CREATE TABLE {schema}.movements (
                id SERIAL PRIMARY KEY,
                process_id VARCHAR(255) REFERENCES {schema}.main(process_id),
                movement_at TIMESTAMP,
                destination_id VARCHAR(255),
                destination_type VARCHAR(50)
            );
        """)

        pg_conn.commit()
        print("✅ Esquema híbrido actualizado creado exitosamente.")
    except ProgrammingError as e:
        print(f"❌ Error de SQL al crear las tablas.", file=sys.stderr)
        print(f"Detalle: {e}", file=sys.stderr)
        pg_conn.rollback()
        sys.exit(1)


def process_user_data(user_obj, pg_cursor, caches):
    """
    Normaliza e inserta datos de usuario usando una caché en memoria para evitar escrituras redundantes.
    """
    if not user_obj or 'user' not in user_obj or not user_obj['user']:
        return None
    user = user_obj['user']
    user_id = user.get('id')
    if not user_id:
        return None
    
    # --- OPTIMIZACIÓN: Si ya procesamos este usuario, salimos rápido ---
    if user_id in caches['users']:
        return user_id

    tables = config.TABLE_NAMES
    
    # Procesar y cachear Area
    if user.get('area') and user['area'].get('id'):
        area_id = user['area']['id']
        if area_id not in caches['areas']:
            pg_cursor.execute(f"INSERT INTO public.{tables['areas']} (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;", (area_id, user['area'].get('name')))
            caches['areas'].add(area_id)

    # Procesar y cachear Subarea
    if user.get('subarea') and user['subarea'].get('id'):
        subarea_id = user['subarea']['id']
        if subarea_id not in caches['subareas']:
            pg_cursor.execute(f"INSERT INTO public.{tables['subareas']} (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;", (subarea_id, user['subarea'].get('name')))
            caches['subareas'].add(subarea_id)
            
    # Procesar y cachear Rol
    if user.get('role') and user['role'].get('id'):
        role_id = user['role']['id']
        if role_id not in caches['roles']:
            pg_cursor.execute(f"INSERT INTO public.{tables['roles']} (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;", (role_id, user['role'].get('name')))
            caches['roles'].add(role_id)

    # Insertar Usuario principal y cachearlo
    pg_cursor.execute(
        f"INSERT INTO public.{tables['users']} (id, email, firstname, lastname, area_id, subarea_id, role_id) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING;",
        (user_id, user.get('email'), user.get('firstname'), user.get('lastname'), user.get('area', {}).get('id'), user.get('subarea', {}).get('id'), user.get('role', {}).get('id'))
    )
    caches['users'].add(user_id)
    
    # Procesar y cachear Grupos
    if user.get('groups'):
        for group in user['groups']:
            if group and group.get('id'):
                group_id = group['id']
                if group_id not in caches['groups']:
                    pg_cursor.execute(f"INSERT INTO public.{tables['groups']} (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;", (group_id, group.get('name')))
                    caches['groups'].add(group_id)
                
                # La tabla pivote user_groups no necesita caché, ON CONFLICT se encarga.
                pg_cursor.execute(f"INSERT INTO public.{tables['user_groups']} (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (user_id, group_id))
    
    return user_id


def process_customer_data(customer_id, pg_cursor, caches):
    """
    Inserta un customer ID en la tabla pública de clientes si no ha sido procesado antes.
    """
    if not customer_id or customer_id in caches['customers']:
        return
    
    tables = config.TABLE_NAMES
    pg_cursor.execute(f"INSERT INTO public.{tables['customers']} (id) VALUES (%s) ON CONFLICT (id) DO NOTHING;", (customer_id,))
    caches['customers'].add(customer_id)


def process_initiator_fields(record_id, fields_obj, pg_cursor):
    """Procesa el objeto initiatorFields e inserta sus datos."""
    if not fields_obj:
        return
    for key, value in fields_obj.items():
        if isinstance(value, dict):
            pg_cursor.execute(
                """
                INSERT INTO initiator_fields (record_id, field_key, field_id, field_name)
                VALUES (%s, %s, %s, %s);
                """,
                (record_id, key, value.get('id'), value.get('name'))
            )

def process_document_lists(record_id, doc_list, doc_type, pg_cursor):
    """Procesa las listas 'documents' e 'internalDocuments'."""
    if not doc_list:
        return
    for doc in doc_list:
        if isinstance(doc, dict):
             # Asumimos que cada documento en el array tiene al menos un 'id'.
             # Si la estructura fuera más compleja, se añadirían más campos aquí.
            pg_cursor.execute(
                """
                INSERT INTO process_documents (record_id, doc_type, document_id)
                VALUES (%s, %s, %s);
                """,
                (record_id, doc_type, doc.get('id'))
            )

def process_last_movement(record_id, movement_obj, pg_cursor):
    """Procesa el objeto lastMovement y aplana sus datos más importantes."""
    if not movement_obj:
        return
    
    # Nos aseguramos de que si 'user' es null, obtengamos un {} por defecto.
    origin_user = movement_obj.get('origin', {}).get('user') or {}
    dest_user = movement_obj.get('destination', {}).get('user') or {}
    
    # Extraer nombres completos para simplicidad
    # Ahora esto es seguro, porque en el peor de los casos, user es {}
    origin_name = f"{origin_user.get('firstname', '')} {origin_user.get('lastname', '')}".strip()
    dest_name = f"{dest_user.get('firstname', '')} {dest_user.get('lastname', '')}".strip()

    pg_cursor.execute(
        """
        INSERT INTO last_movements 
            (record_id, origin_user_id, origin_user_name, destination_user_id, destination_user_name, destination_area_name, destination_subarea_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (record_id) DO NOTHING;
        """,
        (
            record_id,
            origin_user.get('id'),
            origin_name,
            dest_user.get('id'),
            dest_name,
            dest_user.get('area', {}).get('name'),
            dest_user.get('subarea', {}).get('name')
        )
    )
    # ON CONFLICT (record_id) DO NOTHING para mayor robustez,
    # ya que la relación es 1 a 1 y no debería fallar si se re-ejecuta.

def migrate_collection(mongo_db, pg_cursor, pg_conn):
    """
    Migra la colección con la nueva nomenclatura y la entidad de clientes.
    """
    print("\n🚚  Iniciando migración de documentos (v2)...")
    source_collection = mongo_db[config.MONGO_SOURCE_COLLECTION]
    schema = config.POC_SCHEMA_NAME
    BATCH_SIZE = config.BATCH_SIZE
    
    total_docs = source_collection.count_documents({})
    if total_docs == 0:
        print(f"\n⚠️  ADVERTENCIA: No se encontraron documentos.")
        return
    
    print(f"   - Se encontraron {total_docs} documentos. Migrando en lotes de {BATCH_SIZE}...")
    
    caches = {
        'users': set(),
        'areas': set(),
        'subareas': set(),
        'roles': set(),
        'groups': set(),
        'customers': set()
    }

    main_batch = []
    movements_batch = []
    initiator_fields_batch = []
    documents_batch = []
    last_movements_batch = []

    documents_to_migrate = source_collection.find(no_cursor_timeout=True)
    count = 0
    
    for doc in documents_to_migrate:
        count += 1
        process_id = str(doc.get('_id'))
        
        created_by_id = process_user_data(doc.get('createdBy'), pg_cursor, caches)
        updated_by_id = process_user_data(doc.get('updatedBy'), pg_cursor, caches)
        process_customer_data(doc.get('customerId'), pg_cursor, caches)
        
        starter = doc.get('processStarter', {})
        main_batch.append((
            process_id, doc.get('processNumber'), doc.get('processTypeName'),
            doc.get('processAddress'), doc.get('processTypeId'), doc.get('customerId'),
            doc.get('deleted'), doc.get('createdAt'), doc.get('updatedAt'),
            doc.get('processDate'), doc.get('lumbreStatusName'), starter.get('id'),
            starter.get('name'), starter.get('starterType'), created_by_id, updated_by_id
        ))

        if doc.get('movements'):
            for movement in doc['movements']:
                movements_batch.append((process_id, movement.get('at'), movement.get('id'), movement.get('to')))
        
        if doc.get('initiatorFields'):
            for key, value in doc.get('initiatorFields').items():
                if isinstance(value, dict):
                    initiator_fields_batch.append((process_id, key, value.get('id'), value.get('name')))

        if doc.get('documents'):
            for document in doc.get('documents'):
                if isinstance(document, dict):
                    documents_batch.append((process_id, 'external', document.get('id')))

        if doc.get('internalDocuments'):
            for document in doc.get('internalDocuments'):
                if isinstance(document, dict):
                    documents_batch.append((process_id, 'internal', document.get('id')))
        
        if doc.get('lastMovement'):
            lm = doc.get('lastMovement')
            origin_user = lm.get('origin', {}).get('user') or {}
            dest_user = lm.get('destination', {}).get('user') or {}
            origin_name = f"{origin_user.get('firstname', '')} {origin_user.get('lastname', '')}".strip()
            dest_name = f"{dest_user.get('firstname', '')} {dest_user.get('lastname', '')}".strip()
            last_movements_batch.append((
                process_id, origin_user.get('id'), origin_name, dest_user.get('id'), dest_name,
                dest_user.get('area', {}).get('name'), dest_user.get('subarea', {}).get('name')
            ))

        print(f"\r   -> Documentos procesados: {count}/{total_docs}", end="", flush=True)

        if count % BATCH_SIZE == 0:
            if main_batch:
                sql = f"INSERT INTO {schema}.main (process_id, process_number, process_type_name, process_address, process_type_id, customer_id, deleted, created_at, updated_at, process_date, lumbre_status_name, starter_id, starter_name, starter_type, created_by_user_id, updated_by_user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (process_id) DO NOTHING"
                pg_cursor.executemany(sql, main_batch)
                main_batch = []
            if movements_batch:
                pg_cursor.executemany(f"INSERT INTO {schema}.movements (process_id, movement_at, destination_id, destination_type) VALUES (%s,%s,%s,%s)", movements_batch)
                movements_batch = []
            if initiator_fields_batch:
                pg_cursor.executemany(f"INSERT INTO {schema}.initiator_fields (process_id, field_key, field_id, field_name) VALUES (%s,%s,%s,%s)", initiator_fields_batch)
                initiator_fields_batch = []
            if documents_batch:
                pg_cursor.executemany(f"INSERT INTO {schema}.process_documents (process_id, doc_type, document_id) VALUES (%s,%s,%s)", documents_batch)
                documents_batch = []
            if last_movements_batch:
                pg_cursor.executemany(f"INSERT INTO {schema}.last_movements (process_id, origin_user_id, origin_user_name, destination_user_id, destination_user_name, destination_area_name, destination_subarea_name) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (process_id) DO NOTHING", last_movements_batch)
                last_movements_batch = []
            
            pg_conn.commit()

    print("\n   -> Insertando lotes finales...")
    if main_batch:
        sql = f"INSERT INTO {schema}.main (process_id, process_number, process_type_name, process_address, process_type_id, customer_id, deleted, created_at, updated_at, process_date, lumbre_status_name, starter_id, starter_name, starter_type, created_by_user_id, updated_by_user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (process_id) DO NOTHING"
        pg_cursor.executemany(sql, main_batch)
    if movements_batch:
        pg_cursor.executemany(f"INSERT INTO {schema}.movements (process_id, movement_at, destination_id, destination_type) VALUES (%s,%s,%s,%s)", movements_batch)
    if initiator_fields_batch:
        pg_cursor.executemany(f"INSERT INTO {schema}.initiator_fields (process_id, field_key, field_id, field_name) VALUES (%s,%s,%s,%s)", initiator_fields_batch)
    if documents_batch:
        pg_cursor.executemany(f"INSERT INTO {schema}.process_documents (process_id, doc_type, document_id) VALUES (%s,%s,%s)", documents_batch)
    if last_movements_batch:
        pg_cursor.executemany(f"INSERT INTO {schema}.last_movements (process_id, origin_user_id, origin_user_name, destination_user_id, destination_user_name, destination_area_name, destination_subarea_name) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (process_id) DO NOTHING", last_movements_batch)
    
    pg_conn.commit()
    print(f"✅ Migración de {count} documentos completada.")


def main():
    
    print("🚀 Iniciando el script de migración de MongoDB a PostgreSQL...")
    
    mongo_db = connect_to_mongo()
    pg_conn, pg_cursor = connect_to_postgres()

    try:
        # 1. Preparar la base de datos de destino
        create_postgres_tables(pg_cursor, pg_conn)

        # 2. Iniciar la lógica de migración
        migrate_collection(mongo_db, pg_cursor, pg_conn)

    finally:
        print("\n🔒 Cerrando conexiones...")
        pg_cursor.close()
        pg_conn.close()
        print("✅ Conexiones cerradas correctamente.")

if __name__ == "__main__":
    main()