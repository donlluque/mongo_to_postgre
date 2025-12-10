"""
Migrador para la colección lml_usersgroups_mesa4core.

Implementa la interfaz BaseMigrator para transformar documentos de grupos
desde MongoDB hacia el schema PostgreSQL 'lml_usersgroups'. 

RESPONSABILIDAD:
Este es un migrador de tipo 'truth_source', pero con dependencia de lml_users:
- NO consume datos de otros schemas (extract_shared_entities retorna vacío)
- ES la fuente de verdad para grupos y membresías
- DEPENDE de lml_users.main para las FKs de members.user_id

ARQUITECTURA DEL SCHEMA lml_usersgroups:
- main: Catálogo de grupos
- members: Relación N:M con usuarios (group_id, user_id)

DECISIONES DE DISEÑO:
- Grupos con UPSERT (DO NOTHING): Preserva primer insert
- Membresías con DELETE + INSERT: Sincroniza estado completo por grupo
- Validación de FKs: Loguear warning si user_id no existe en lml_users.main
- Snapshots NO migrados: Solo extraer created_by/updated_by IDs

Uso (desde mongomigra.py):
    migrator = LmlUsersgroupsMigrator(schema='lml_usersgroups')
    
    shared = migrator.extract_shared_entities(doc, cursor, caches)  # {}
    data = migrator.extract_data(doc, shared)
    
    # Acumular en batches... 
    migrator.insert_batches(batches, cursor)
"""


from datetime import datetime
from psycopg2.extras import execute_values
from .base import BaseMigrator
import config


class LmlUsersgroupsMigrator(BaseMigrator):
    """
    Migrador específico para lml_usersgroups_mesa4core.
    """
    
    def __init__(self, schema='lml_usersgroups'):
        super().__init__(schema)
        # Cola para usuarios fantasmas (solo auditoría)
        self.ghost_users_queue = []
    
    # =========================================================================
    # MÉTODOS PÚBLICOS - EXTRACCIÓN Y CACHÉ
    # =========================================================================
    
    def extract_shared_entities(self, doc, cursor, caches):
        """
        1. Carga caché de usuarios válidos.
        2. Procesa usuarios de auditoría (crea fantasmas si faltan).
        3. Retorna el set de usuarios para filtrar miembros en el siguiente paso.
        """
        # A. Cargar caché (lml_users.main)
        if 'valid_user_ids' not in caches:
            try:
                cursor.execute("SELECT id FROM lml_users.main")
                caches['valid_user_ids'] = {row[0] for row in cursor.fetchall()}
            except Exception:
                caches['valid_user_ids'] = set()

        valid_users = caches['valid_user_ids']

        # B. Procesar auditoría (Ghost Users)
        created_by = self._process_ghost_user(doc.get('createdBy'), valid_users)
        updated_by = self._process_ghost_user(doc.get('updatedBy'), valid_users)

        return {
            'created_by_user_id': created_by,
            'updated_by_user_id': updated_by,
            'customer_id': doc.get('customerId'),
            # Pasamos el set de usuarios válidos para filtrar miembros
            'valid_users_ref': valid_users
        }
    
    def _process_ghost_user(self, snapshot, valid_users_set):
        """
        Verifica si el usuario existe. Si no, lo encola para crearlo.
        """
        if not snapshot or not isinstance(snapshot, dict): return None
        
        user_data = snapshot.get('user', {})
        user_id = None
        
        if isinstance(user_data, (str, int)):
            user_id = str(user_data)
        elif isinstance(user_data, dict):
            user_id = user_data.get('id') or user_data.get('_id')
            if isinstance(user_id, dict): user_id = user_id.get('$oid')
        
        if not user_id: return None
        user_id = str(user_id)
        if len(user_id) < 5: return None

        # Si no existe, a la cola
        if user_id not in valid_users_set:
            firstname = None; lastname = None; email = None; username = None
            if isinstance(user_data, dict):
                firstname = user_data.get('firstname') or 'Restored'
                lastname = user_data.get('lastname') or 'User'
                email = user_data.get('email')
                username = user_data.get('username')

            self.ghost_users_queue.append((user_id, firstname, lastname, email, username))
            valid_users_set.add(user_id)
            
        return user_id

    def extract_data(self, doc, shared_entities):
        """
        Extrae datos y FILTRA miembros inválidos.
        """
        group_id = self.get_primary_key_from_doc(doc)
        valid_users = shared_entities['valid_users_ref']
        
        return {
            'main': self._extract_main_record(doc, shared_entities),
            'related': {
                # Pasamos valid_users para filtrar
                'members': self._extract_members(doc, group_id, valid_users)
            }
        }
    
    # =========================================================================
    # MÉTODOS PÚBLICOS - INSERCIÓN (OPTIMIZADA)
    # =========================================================================
    
    def insert_batches(self, batches, cursor, caches=None):
        """
        1. Inserta Ghost Users.
        2. Inserta Grupos.
        3. Sincroniza Miembros.
        """
        # 1. Ghost Users (Auditoría)
        if self.ghost_users_queue:
            try:
                execute_values(
                    cursor,
                    """INSERT INTO lml_users.main (id, firstname, lastname, email, username, deleted, created_at, updated_at)
                    VALUES %s ON CONFLICT (id) DO NOTHING""",
                    self.ghost_users_queue,
                    template="(%s, %s, %s, %s, %s, TRUE, NOW(), NOW())",
                    page_size=1000
                )
                
                if caches and 'valid_user_ids' in caches:
                    caches['valid_user_ids'].update([u[0] for u in self.ghost_users_queue])
                
                self.ghost_users_queue = []
            except Exception as e:
                print(f"   ❌ Error insertando ghost users: {e}")

        # 2. Grupos
        if batches['main']:
            self._insert_main_batch(batches['main'], cursor)
        
        # 3. Miembros
        if batches['related']['members']:
            self._sync_members_batch(batches['related']['members'], cursor)
    
    def initialize_batches(self):
        return {'main': [], 'related': {'members': []}}
    
    def get_primary_key_from_doc(self, doc):
        return str(doc.get('_id'))
    
    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN
    # =========================================================================
    
    def _extract_main_record(self, doc, shared_entities):
        group_id = self.get_primary_key_from_doc(doc)
        
        # Timestamps
        created_at = self._extract_timestamp(doc, 'createdAt')
        updated_at = self._extract_timestamp(doc, 'updatedAt')
        
        return (
            group_id,
            doc.get('name'),
            doc.get('alias'),
            doc.get('deleted', False),
            doc.get('customer_id') or doc.get('customerId'),
            doc.get('lumbre_version') or doc.get('lumbreVersion'),
            doc.get('imported_from_external') or doc.get('importedFromExternal'),
            created_at,
            updated_at,
            shared_entities['created_by_user_id'],
            shared_entities['updated_by_user_id'],
            doc.get('__v')
        )
    
    def _extract_members(self, doc, group_id, valid_users_set):
        """
        Extrae IDs de miembros y FILTRA los que no existen en Postgres.
        """
        members = []
        users_array = doc.get('users', [])
        
        for user_id in users_array:
            if not user_id: continue
            uid = str(user_id)
            
            # FILTRO DE SEGURIDAD: Solo agregamos si el usuario existe realmente.
            # Esto evita errores de FK y evita ensuciar la DB con fantasmas innecesarios.
            if uid in valid_users_set:
                members.append((group_id, uid))
        
        return members
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _extract_timestamp(self, doc, field_name):
        value = doc.get(field_name)
        if not value: return None
        try:
            if isinstance(value, datetime): return value
            if isinstance(value, dict) and '$date' in value: value = value['$date']
            if isinstance(value, str):
                if value.endswith('Z'):
                    fmt = "%Y-%m-%dT%H:%M:%S.%fZ" if '.' in value else "%Y-%m-%dT%H:%M:%SZ"
                    return datetime.strptime(value, fmt)
                if '+' in value or value.count('-') > 2: return datetime.fromisoformat(value)
        except (ValueError, TypeError): return None
        return None
    
    # =========================================================================
    # MÉTODOS PRIVADOS: INSERCIÓN (OPTIMIZADA)
    # =========================================================================
    
    def _insert_main_batch(self, batch, cursor):
        execute_values(cursor, f"""
            INSERT INTO {self.schema}.main 
            (id, name, alias, deleted, customer_id, lumbre_version,
             imported_from_external, created_at, updated_at,
             created_by_user_id, updated_by_user_id, __v)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
        """, batch, page_size=1000)
    
    def _sync_members_batch(self, batch, cursor):
        # 1. Agrupar por group_id
        groups_members = {}
        for group_id, user_id in batch:
            if group_id not in groups_members: groups_members[group_id] = []
            groups_members[group_id].append((group_id, user_id))
        
        # 2. Procesar (DELETE + INSERT)
        # Nota: Aquí no podemos usar execute_values masivo global porque hay que borrar por grupo.
        # Pero sí usamos execute_values para insertar los miembros de cada grupo.
        for group_id, members in groups_members.items():
            # Borrar viejos
            cursor.execute(f"DELETE FROM {self.schema}.members WHERE group_id = %s", (group_id,))
            
            # Insertar nuevos (bulk del grupo)
            if members:
                execute_values(
                    cursor,
                    f"INSERT INTO {self.schema}.members (group_id, user_id) VALUES %s",
                    members
                )