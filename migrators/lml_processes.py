r"""
Módulo de migración para la colección lml_processes_mesa4core.

Este módulo contiene toda la lógica específica para transformar documentos
de la colección MongoDB 'lml_processes_mesa4core' al schema PostgreSQL
'lml_processes'.

Responsabilidades:
- Extraer entidades compartidas (users, customers) de la estructura de Mongo
- Transformar campos específicos de procesos
- Preparar batches para inserción en PostgreSQL

Arquitectura:
- Funciones extract_*: MongoDB document → Python dict/tuple
- Funciones insert_*: Python structures → PostgreSQL (usando cursor)

Uso:
    from collections import lml_processes
    
    # Extraer datos de un documento Mongo
    shared = lml_processes.extract_shared_entities(mongo_doc, cursor, caches)
    main_data = lml_processes.extract_main_record(mongo_doc, shared)
    
    # Insertar en batch
    lml_processes.insert_main_batch(batch, cursor, schema)
"""

import config

# Nombre del schema destino en PostgreSQL
SCHEMA_NAME = "lml_processes"


def extract_user_data(user_obj, cursor, caches):
    """
    Extrae y normaliza datos de usuario desde un objeto user anidado de MongoDB.
    
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
    
    Inserta las entidades en el schema 'public' usando ON CONFLICT DO NOTHING
    para idempotencia. Utiliza caché en memoria para evitar INSERT redundantes.
    
    Args:
        user_obj: Objeto completo del tipo {"user": {...}} desde Mongo
        cursor: Cursor de psycopg2 para ejecutar INSERTs
        caches: Dict de sets para tracking de entidades procesadas
        
    Returns:
        str: El user_id si se procesó exitosamente
        None: Si user_obj es None/vacío o no tiene estructura válida
        
    Side Effects:
        - Inserta en public.areas, public.subareas, public.roles
        - Inserta en public.users
        - Inserta en public.groups y public.user_groups
        - Actualiza los sets en caches
        
    Example:
        >>> caches = {'users': set(), 'areas': set(), ...}
        >>> user_id = extract_user_data(doc['createdBy'], cursor, caches)
        >>> print(user_id)
        'USR001'
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
                
                # Insertar relación user-group (ON CONFLICT maneja duplicados)
                cursor.execute(
                    f"INSERT INTO public.{tables['user_groups']} (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                    (user_id, group_id)
                )
    
    return user_id


def extract_customer_data(customer_id, cursor, caches):
    """
    Inserta un customer_id en la tabla public.customers si no fue procesado.
    
    Los customers en lml_processes son simplemente IDs sin metadatos adicionales.
    Esta función usa caché para evitar INSERTs redundantes.
    
    Args:
        customer_id: ID del cliente desde MongoDB
        cursor: Cursor de psycopg2
        caches: Dict de sets para tracking
        
    Returns:
        None
        
    Side Effects:
        - Inserta en public.customers si customer_id no está en caché
        - Actualiza caches['customers']
    """
    if not customer_id or customer_id in caches['customers']:
        return
    
    tables = config.TABLE_NAMES
    cursor.execute(
        f"INSERT INTO public.{tables['customers']} (id) VALUES (%s) ON CONFLICT (id) DO NOTHING;",
        (customer_id,)
    )
    caches['customers'].add(customer_id)


def extract_shared_entities(doc, cursor, caches):
    """
    Extrae y procesa todas las entidades compartidas de un documento.
    
    Esta función centraliza la extracción de entidades que viven en el
    schema 'public' y son compartidas entre colecciones.
    
    Args:
        doc: Documento completo de MongoDB
        cursor: Cursor de psycopg2
        caches: Dict de sets para tracking de entidades
        
    Returns:
        dict: Contiene los IDs extraídos para uso posterior
            {
                'created_by_user_id': str or None,
                'updated_by_user_id': str or None,
                'customer_id': str or None
            }
    """
    result = {
        'created_by_user_id': extract_user_data(doc.get('createdBy'), cursor, caches),
        'updated_by_user_id': extract_user_data(doc.get('updatedBy'), cursor, caches),
        'customer_id': doc.get('customerId')
    }
    
    # Procesar customer
    extract_customer_data(result['customer_id'], cursor, caches)
    
    return result


def extract_main_record(doc, shared_entities):
    """
    Extrae el registro principal de un documento para la tabla main.
    
    Transforma la estructura flat/anidada de MongoDB al formato de tuple
    requerido por executemany() de psycopg2.
    
    Args:
        doc: Documento de MongoDB
        shared_entities: Dict retornado por extract_shared_entities()
        
    Returns:
        tuple: Valores en el orden de columnas de lml_processes.main
            (process_id, process_number, process_type_name, ..., updated_by_user_id)
    """
    process_id = str(doc.get('_id'))
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


def extract_movements(doc, process_id):
    """
    Extrae la lista de movimientos de un documento.
    
    Args:
        doc: Documento de MongoDB
        process_id: ID del proceso (para la FK)
        
    Returns:
        list: Lista de tuples (process_id, movement_at, destination_id, destination_type)
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


def extract_initiator_fields(doc, process_id):
    """
    Extrae los campos dinámicos del iniciador del proceso.
    
    Args:
        doc: Documento de MongoDB
        process_id: ID del proceso
        
    Returns:
        list: Lista de tuples (process_id, field_key, field_id, field_name)
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


def extract_documents(doc, process_id):
    """
    Extrae documentos externos e internos asociados al proceso.
    
    Args:
        doc: Documento de MongoDB
        process_id: ID del proceso
        
    Returns:
        list: Lista de tuples (process_id, doc_type, document_id)
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


def extract_last_movement(doc, process_id):
    """
    Extrae el último movimiento del proceso (relación 1:1).
    
    Args:
        doc: Documento de MongoDB
        process_id: ID del proceso
        
    Returns:
        tuple or None: (process_id, origin_user_id, origin_user_name, ...) o None si no existe
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


def insert_main_batch(batch, cursor, schema):
    """
    Inserta un batch de registros principales en la tabla main.
    
    Args:
        batch: Lista de tuples retornadas por extract_main_record()
        cursor: Cursor de psycopg2
        schema: Nombre del schema ('lml_processes')
    """
    if not batch:
        return
    
    sql = f"""
        INSERT INTO {schema}.main 
        (process_id, process_number, process_type_name, process_address, 
         process_type_id, customer_id, deleted, created_at, updated_at, 
         process_date, lumbre_status_name, starter_id, starter_name, 
         starter_type, created_by_user_id, updated_by_user_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    cursor.executemany(sql, batch)


def insert_movements_batch(batch, cursor, schema):
    """Inserta batch de movimientos."""
    if not batch:
        return
    cursor.executemany(
        f"INSERT INTO {schema}.movements (process_id, movement_at, destination_id, destination_type) VALUES (%s,%s,%s,%s)",
        batch
    )


def insert_initiator_fields_batch(batch, cursor, schema):
    """Inserta batch de initiator fields."""
    if not batch:
        return
    cursor.executemany(
        f"INSERT INTO {schema}.initiator_fields (process_id, field_key, field_id, field_name) VALUES (%s,%s,%s,%s)",
        batch
    )


def insert_documents_batch(batch, cursor, schema):
    """Inserta batch de documentos."""
    if not batch:
        return
    cursor.executemany(
        f"INSERT INTO {schema}.process_documents (process_id, doc_type, document_id) VALUES (%s,%s,%s)",
        batch
    )


def insert_last_movements_batch(batch, cursor, schema):
    """Inserta batch de últimos movimientos."""
    if not batch:
        return
    cursor.executemany(
        f"""INSERT INTO {schema}.last_movements 
            (process_id, origin_user_id, origin_user_name, destination_user_id, 
             destination_user_name, destination_area_name, destination_subarea_name) 
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        batch
    )