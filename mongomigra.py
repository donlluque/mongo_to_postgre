r"""
Script principal de migración de colecciones MongoDB a PostgreSQL.

Este script orquesta el proceso de migración de datos desde MongoDB hacia
PostgreSQL. La lógica específica de transformación está delegada a módulos
en el paquete 'migrators/', permitiendo migrar múltiples colecciones con
diferentes estructuras.

Arquitectura:
- mongomigra.py: Infraestructura (conexiones, batching, progreso)
- migrators/*.py: Lógica de transformación específica por colección

Flujo de Ejecución:
1. Conectar a MongoDB y PostgreSQL
2. Cargar módulo migrador específico (migrators/lml_processes.py)
3. Iterar sobre documentos en batches
4. Extraer entidades compartidas (public.*)
5. Extraer datos específicos (schema específico)
6. Insertar en batches y commit

Prerrequisitos:
- Base de datos creada (mesamongo)
- Estructura de tablas creada (ejecutar dbsetup.py primero)

Uso:
    python mongomigra.py
    
    # Verificar migración
    psql -d mesamongo -c "SELECT COUNT(*) FROM lml_processes.main;"

Optimizaciones:
- Batch processing: Inserciones de 500 registros por commit
- Caché en memoria: Evita procesamiento redundante de entidades compartidas
- Cursor sin timeout: Soporta migraciones de larga duración
"""

import sys
import psycopg2
from pymongo import MongoClient, CursorType
from pymongo.errors import ConnectionFailure
from psycopg2 import OperationalError, ProgrammingError

import config
from migrators import lml_processes as migrator


def connect_to_mongo():
    """
    Establece conexión a MongoDB usando credenciales de config.py.
    
    Configuración:
    - Timeout de selección de servidor: 5 segundos
    - Ping inicial para validar conexión
    
    Returns:
        Database: Objeto de base de datos de pymongo
        
    Raises:
        ConnectionFailure: Si no puede conectar a MongoDB
        SystemExit: Termina el programa con código 1
    """
    try:
        print("🔌 Conectando a MongoDB...")
        client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[config.MONGO_DATABASE_NAME]
        print("✅ Conexión a MongoDB exitosa")
        return db
    except ConnectionFailure as e:
        print(f"❌ Error de conexión a MongoDB", file=sys.stderr)
        print(f"   Detalle: {e}", file=sys.stderr)
        sys.exit(1)


def connect_to_postgres():
    """
    Establece conexión a PostgreSQL usando credenciales de config.py.
    
    Returns:
        tuple: (conexión, cursor) de psycopg2
        
    Raises:
        OperationalError: Si no puede conectar a PostgreSQL
        SystemExit: Termina el programa con código 1
    """
    try:
        print("🔌 Conectando a PostgreSQL...")
        conn = psycopg2.connect(**config.POSTGRES_CONFIG)
        cursor = conn.cursor()
        print("✅ Conexión a PostgreSQL exitosa")
        return conn, cursor
    except OperationalError as e:
        print(f"❌ Error de conexión a PostgreSQL", file=sys.stderr)
        print(f"   Detalle: {e}", file=sys.stderr)
        sys.exit(1)


def migrate_collection(mongo_db, pg_cursor, pg_conn, collection_name):
    """
    Orquesta la migración de una colección específica.
    
    Esta función maneja:
    - Iteración sobre documentos de MongoDB
    - Acumulación de registros en batches
    - Coordinación con el módulo migrador específico
    - Commits periódicos a PostgreSQL
    - Reporte de progreso
    
    El patrón de procesamiento es:
        Para cada documento:
            1. Extraer entidades compartidas → INSERT en public.*
            2. Extraer datos específicos → Acumular en batches
            3. Cada N documentos → executemany() + commit
    
    Args:
        mongo_db: Base de datos de pymongo
        pg_cursor: Cursor de psycopg2
        pg_conn: Conexión de psycopg2
        collection_name: Nombre de la colección a migrar
        
    Raises:
        KeyError: Si collection_name no existe en config.COLLECTIONS
    """
    print(f"\n🚚 Iniciando migración de colección '{collection_name}'...")
    
    # Validar que la colección esté configurada
    if collection_name not in config.COLLECTIONS:
        print(f"❌ Colección '{collection_name}' no encontrada en config.COLLECTIONS", file=sys.stderr)
        sys.exit(1)
    
    collection_config = config.COLLECTIONS[collection_name]
    schema = collection_config['postgres_schema']
    
    source_collection = mongo_db[collection_name]
    batch_size = config.BATCH_SIZE
    
    # Contar documentos totales
    total_docs = source_collection.count_documents({})
    if total_docs == 0:
        print(f"⚠️  Advertencia: No se encontraron documentos en '{collection_name}'")
        return
    
    print(f"   📊 Total de documentos: {total_docs:,}")
    print(f"   📦 Tamaño de batch: {batch_size}")
    print(f"   🎯 Schema destino: {schema}")
    
    # Inicializar cachés para evitar procesamiento redundante
    caches = {
        'users': set(),
        'areas': set(),
        'subareas': set(),
        'roles': set(),
        'groups': set(),
        'customers': set()
    }
    
    # Inicializar batches acumuladores
    main_batch = []
    movements_batch = []
    initiator_fields_batch = []
    documents_batch = []
    last_movements_batch = []
    
    # Cursor sin timeout para migraciones largas (>30 min)
    documents_to_migrate = source_collection.find(
        cursor_type=CursorType.NON_TAILABLE
    )
    count = 0
    
    try:
        for doc in documents_to_migrate:
            count += 1
            process_id = str(doc.get('_id'))
            
            # PASO 1: Extraer y procesar entidades compartidas
            # Esto inserta directamente en public.* usando ON CONFLICT
            shared_entities = migrator.extract_shared_entities(doc, pg_cursor, caches)
            
            # PASO 2: Extraer datos específicos (acumular en batches)
            main_batch.append(migrator.extract_main_record(doc, shared_entities))
            movements_batch.extend(migrator.extract_movements(doc, process_id))
            initiator_fields_batch.extend(migrator.extract_initiator_fields(doc, process_id))
            documents_batch.extend(migrator.extract_documents(doc, process_id))
            
            last_movement = migrator.extract_last_movement(doc, process_id)
            if last_movement:
                last_movements_batch.append(last_movement)
            
            # Mostrar progreso en la misma línea
            if count % 100 == 0 or count % batch_size == 0:
                print(f"\r   ⏳ Procesados: {count:,}/{total_docs:,} ({count*100//total_docs}%)", end="", flush=True)
            
            # PASO 3: Insertar y commit cada N documentos
            if count % batch_size == 0:
                migrator.insert_main_batch(main_batch, pg_cursor, schema)
                migrator.insert_movements_batch(movements_batch, pg_cursor, schema)
                migrator.insert_initiator_fields_batch(initiator_fields_batch, pg_cursor, schema)
                migrator.insert_documents_batch(documents_batch, pg_cursor, schema)
                migrator.insert_last_movements_batch(last_movements_batch, pg_cursor, schema)
                
                pg_conn.commit()
                
                # Limpiar batches para el próximo ciclo
                main_batch = []
                movements_batch = []
                initiator_fields_batch = []
                documents_batch = []
                last_movements_batch = []
        
        # PASO 4: Insertar registros finales (si count no es múltiplo exacto de batch_size)
        print("\n   💾 Insertando registros finales...")
        migrator.insert_main_batch(main_batch, pg_cursor, schema)
        migrator.insert_movements_batch(movements_batch, pg_cursor, schema)
        migrator.insert_initiator_fields_batch(initiator_fields_batch, pg_cursor, schema)
        migrator.insert_documents_batch(documents_batch, pg_cursor, schema)
        migrator.insert_last_movements_batch(last_movements_batch, pg_cursor, schema)
        
        pg_conn.commit()
        
        print(f"\n✅ Migración completada: {count:,} documentos procesados")
        
        # Reporte de entidades compartidas procesadas
        print(f"\n📋 Resumen de entidades compartidas:")
        print(f"   👥 Usuarios: {len(caches['users']):,}")
        print(f"   🏢 Áreas: {len(caches['areas']):,}")
        print(f"   📁 Subareas: {len(caches['subareas']):,}")
        print(f"   🎭 Roles: {len(caches['roles']):,}")
        print(f"   👪 Grupos: {len(caches['groups']):,}")
        print(f"   🏪 Clientes: {len(caches['customers']):,}")
        
    finally:
        # Cerrar cursor de MongoDB para liberar recursos
        documents_to_migrate.close()


def main():
    """
    Función principal que coordina el flujo completo de migración.
    
    Secuencia:
    1. Conectar a ambas bases de datos
    2. Ejecutar migración de colección configurada
    3. Cerrar conexiones limpiamente
    
    Exit Codes:
        0: Éxito
        1: Error de conexión o migración
    """
    print("=" * 70)
    print("🚀 SISTEMA DE MIGRACIÓN MONGODB → POSTGRESQL")
    print("=" * 70)
    print(f"📍 MongoDB: {config.MONGO_DATABASE_NAME}")
    print(f"📍 PostgreSQL: {config.POSTGRES_CONFIG['dbname']}")
    print("=" * 70)
    
    # Por ahora migramos solo lml_processes, después será parametrizable
    collection_name = "lml_processes_mesa4core"
    
    mongo_db = connect_to_mongo()
    pg_conn, pg_cursor = connect_to_postgres()
    
    try:
        migrate_collection(mongo_db, pg_cursor, pg_conn, collection_name)
        
        print("\n" + "=" * 70)
        print("✅ PROCESO COMPLETADO EXITOSAMENTE")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ Error durante la migración: {e}", file=sys.stderr)
        pg_conn.rollback()
        sys.exit(1)
        
    finally:
        print("\n🔒 Cerrando conexiones...")
        pg_cursor.close()
        pg_conn.close()
        print("✅ Conexiones cerradas correctamente")


if __name__ == "__main__":
    main()