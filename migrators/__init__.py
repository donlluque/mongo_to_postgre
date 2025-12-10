"""
Migradores para transformar colecciones MongoDB a schemas PostgreSQL.

Cada migrador implementa la interfaz BaseMigrator y se carga dinámicamente
en runtime según la colección seleccionada.

Estructura:
    base.py: Clase abstracta BaseMigrator
    lml_users.py: Migrador para lml_users_mesa4core
    lml_usersgroups.py: Migrador para lml_usersgroups_mesa4core
    lml_processes.py: Migrador para lml_processes_mesa4core
    lml_listbuilder.py: Migrador para lml_listbuilder_mesa4core
    lml_formbuilder.py: Migrador para lml_formbuilder_mesa4core

Los migradores son instanciados por load_migrator_for_collection() en
mongomigra.py usando importlib.import_module() para carga dinámica.

Tipos de migradores:
    - truth_source: No consume datos de otros schemas (ej: lml_users)
    - consumer: Depende de otros schemas vía FKs (ej: lml_processes)

Interfaz requerida (ver BaseMigrator):
    - extract_shared_entities(doc, cursor, caches)
    - extract_data(doc, shared_entities)
    - insert_batches(batches, cursor, caches)
    - initialize_batches()
    - get_primary_key_from_doc(doc)
"""
