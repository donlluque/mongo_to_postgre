"""

Migrador para la colección lml_processes_mesa4core.

Implementa la interfaz BaseMigrator para transformar documentos de la
colección MongoDB 'lml_processes_mesa4core' al schema PostgreSQL 'lml_processes'.

RESPONSABILIDAD:

Este es un migrador de tipo 'consumer', lo que significa que:
- DEPENDE de lml_users (debe migrarse primero)
- NO inserta usuarios, solo extrae IDs y valida FKs
- Consume datos de snapshots (createdBy/updatedBy) para auditoría

Arquitectura:
- Hereda de BaseMigrator (contrato común)
- Métodos públicos: Interfaz requerida por mongomigra.py
- Métodos privados: Lógica específica de transformación

Uso (desde mongomigra.py):
- migrator = LmlProcessesMigrator(schema='lml_processes')
- shared = migrator.extract_shared_entities(doc, cursor, caches)
- data = migrator.extract_data(doc, shared)
- # Acumular en batches...
- migrator.insert_batches(batches, cursor)

"""

import config
from psycopg2.extras import execute_values
from .base import BaseMigrator
from datetime import datetime


class LmlProcessesMigrator(BaseMigrator):
    """
    Migrador específico para lml_processes_mesa4core.
    Transforma documentos con estructura de procesos/trámites desde MongoDB
    a un modelo relacional normalizado en PostgreSQL.
    """

    def __init__(self, schema="lml_processes"):
        """
        Constructor del migrador.
        Args:
            schema: Nombre del schema destino en PostgreSQL
        """
        super().__init__(schema)
        # Cola en memoria para acumular usuarios fantasmas antes de insertar en lote
        self.ghost_users_queue = []

    # =========================================================================
    # MÉTODOS PÚBLICOS - EXTRACCIÓN Y CACHÉ
    # =========================================================================

    def extract_shared_entities(self, doc, cursor, caches):
        """
        Extrae IDs. Si falta un usuario, lo guarda en memoria (cola) para insertarlo después.
        """
        # A. Cargar caché inicial de usuarios (Solo la primera vez)
        # VERIFICADO: Usa lml_users.main
        if "valid_user_ids" not in caches:
            try:
                cursor.execute("SELECT id FROM lml_users.main")
                caches["valid_user_ids"] = {row[0] for row in cursor.fetchall()}
            except Exception:
                caches["valid_user_ids"] = set()

        valid_users = caches["valid_user_ids"]

        # B. Procesar createdBy/updatedBy
        return {
            "created_by_user_id": self._process_ghost_user(
                doc.get("createdBy"), valid_users
            ),
            "updated_by_user_id": self._process_ghost_user(
                doc.get("updatedBy"), valid_users
            ),
            "customer_id": doc.get("customerId"),
        }

    def _process_ghost_user(self, snapshot, valid_users_set):
        """
        Verifica si el usuario existe. Si no, extrae sus datos y lo agrega a la cola de espera.
        """
        if not snapshot or not isinstance(snapshot, dict):
            return None

        user_data = snapshot.get("user", {})
        user_id = None

        # Extracción del ID
        if isinstance(user_data, (str, int)):
            user_id = str(user_data)
        elif isinstance(user_data, dict):
            user_id = user_data.get("id") or user_data.get("_id")
            if isinstance(user_id, dict):
                user_id = user_id.get("$oid")

        if not user_id:
            return None
        user_id = str(user_id)

        # Filtro de basura (IDs muy cortos)
        if len(user_id) < 5:
            return None

        # --- LÓGICA CORE: COMPARACIÓN EN MEMORIA ---
        if user_id not in valid_users_set:

            # Preparamos datos para restaurar
            firstname = None
            lastname = None
            email = None
            username = None

            if isinstance(user_data, dict):
                firstname = (
                    user_data.get("firstname")
                    or user_data.get("firstName")
                    or "Restored"
                )
                lastname = (
                    user_data.get("lastname") or user_data.get("lastName") or "User"
                )
                email = user_data.get("email")
                username = user_data.get("username") or user_data.get("userName")

            # 1. Agregamos a la COLA
            self.ghost_users_queue.append(
                (user_id, firstname, lastname, email, username)
            )

            # 2. Agregamos al SET inmediatamente
            valid_users_set.add(user_id)

        return user_id

    def _parse_timestamp(self, value):
        """
        Convierte timestamp de MongoDB a formato compatible con PostgreSQL.

        Formatos soportados:
        - datetime nativo de pymongo (el más común)
        - ISO8601 con 'Z': '2021-03-22T07:49:18.242Z'
        - ISO8601 con timezone: '2022-06-02T13:54:12.273+00:00'
        - Extended JSON: {'$date': '...'}

        Returns:
            datetime|None: Timestamp parseado o None
        """
        if not value:
            return None

        try:
            # Caso 1: Ya es datetime (pymongo lo convierte automáticamente)
            if isinstance(value, datetime):
                return value

            # Caso 2: Extended JSON
            if isinstance(value, dict) and "$date" in value:
                value = value["$date"]

            # Caso 3: String ISO8601
            if isinstance(value, str):
                # Con 'Z' al final
                if value.endswith("Z"):
                    if "." in value:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
                    else:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")

                # Con timezone explícito
                if "+" in value or value.count("-") > 2:
                    return datetime.fromisoformat(value)

        except (ValueError, TypeError):
            return None

        return None

    def extract_data(self, doc, shared_entities):
        """
        Extrae todos los datos del documento en estructura normalizada.
        """
        process_id = self.get_primary_key_from_doc(doc)

        # Extraer last_movement (puede ser None)
        last_movement = self._extract_last_movement(doc, process_id)

        return {
            "main": self._extract_main_record(doc, shared_entities),
            "related": {
                "movements": self._extract_movements(doc, process_id),
                "initiator_fields": self._extract_initiator_fields(doc, process_id),
                "process_documents": self._extract_documents(doc, process_id),
                "last_movements": [last_movement] if last_movement else [],
            },
        }

    # =========================================================================
    # MÉTODOS PÚBLICOS - INSERCIÓN (OPTIMIZADA)
    # =========================================================================

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
                    page_size=1000,
                )

                if caches and "valid_user_ids" in caches:
                    caches["valid_user_ids"].update(
                        [u[0] for u in self.ghost_users_queue]
                    )

                self.ghost_users_queue = []
            except Exception as e:
                print(f"   ❌ Error insertando lote de ghost users: {e}")
        # --- Inserción Normal ---

        # Insertar tabla main
        if batches["main"]:
            self._insert_main_batch(batches["main"], cursor)

        # Insertar tablas relacionadas dinámicamente
        for table_name, records in batches["related"].items():
            if records:
                method_name = f"_insert_{table_name}_batch"
                insert_method = getattr(self, method_name)
                insert_method(records, cursor)

    def initialize_batches(self):
        return {
            "main": [],
            "related": {
                "movements": [],
                "initiator_fields": [],
                "process_documents": [],
                "last_movements": [],
            },
        }

    def get_primary_key_from_doc(self, doc):
        return str(doc.get("_id"))

    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN DE DATOS (SIN CAMBIOS LÓGICOS)
    # =========================================================================

    def _extract_main_record(self, doc, shared_entities):
        process_id = self.get_primary_key_from_doc(doc)
        starter = doc.get("processStarter", {})

        return (
            process_id,
            doc.get("processNumber"),
            doc.get("processTypeName"),
            doc.get("processAddress"),
            doc.get("processTypeId"),
            shared_entities["customer_id"],
            doc.get("deleted"),
            self._parse_timestamp(doc.get("createdAt")),
            self._parse_timestamp(doc.get("updatedAt")),
            doc.get("processDate"),
            doc.get("lumbreStatusName"),
            starter.get("id"),
            starter.get("name"),
            starter.get("starterType"),
            shared_entities["created_by_user_id"],
            shared_entities["updated_by_user_id"],
        )

    def _extract_movements(self, doc, process_id):
        movements = []
        if doc.get("movements"):
            for movement in doc["movements"]:
                movements.append(
                    (
                        process_id,
                        movement.get("at"),
                        movement.get("id"),
                        movement.get("to"),
                    )
                )
        return movements

    def _extract_initiator_fields(self, doc, process_id):
        fields = []
        if doc.get("initiatorFields"):
            for key, value in doc.get("initiatorFields").items():
                if isinstance(value, dict):
                    fields.append((process_id, key, value.get("id"), value.get("name")))
        return fields

    def _extract_documents(self, doc, process_id):
        documents = []

        # Documentos externos
        if doc.get("documents"):
            for document in doc.get("documents"):
                if isinstance(document, dict):
                    documents.append((process_id, "external", document.get("id")))

        # Documentos internos
        if doc.get("internalDocuments"):
            for document in doc.get("internalDocuments"):
                if isinstance(document, dict):
                    documents.append((process_id, "internal", document.get("id")))

        return documents

    def _extract_last_movement(self, doc, process_id):
        if not doc.get("lastMovement"):
            return None

        lm = doc.get("lastMovement")
        origin_user = lm.get("origin", {}).get("user") or {}
        dest_user = lm.get("destination", {}).get("user") or {}

        origin_name = f"{origin_user.get('firstname', '')} {origin_user.get('lastname', '')}".strip()
        dest_name = (
            f"{dest_user.get('firstname', '')} {dest_user.get('lastname', '')}".strip()
        )

        return (
            process_id,
            origin_user.get("id"),
            origin_name,
            dest_user.get("id"),
            dest_name,
            dest_user.get("area", {}).get("name"),
            dest_user.get("subarea", {}).get("name"),
        )

    # =========================================================================
    # MÉTODOS PRIVADOS: INSERCIÓN (OPTIMIZADA CON execute_values)
    # =========================================================================

    def _insert_main_batch(self, batch, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.main 
            (process_id, process_number, process_type_name, process_address, 
             process_type_id, customer_id, deleted, created_at, updated_at, 
             process_date, lumbre_status_name, starter_id, starter_name, 
             starter_type, created_by_user_id, updated_by_user_id)
            VALUES %s
            ON CONFLICT (process_id) DO NOTHING
            """,
            batch,
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            page_size=1000,
        )

    def _insert_movements_batch(self, batch, cursor):
        execute_values(
            cursor,
            f"INSERT INTO {self.schema}.movements (process_id, movement_at, destination_id, destination_type) VALUES %s",
            batch,
            template="(%s,%s,%s,%s)",
            page_size=1000,
        )

    def _insert_initiator_fields_batch(self, batch, cursor):
        execute_values(
            cursor,
            f"INSERT INTO {self.schema}.initiator_fields (process_id, field_key, field_id, field_name) VALUES %s",
            batch,
            template="(%s,%s,%s,%s)",
            page_size=1000,
        )

    def _insert_process_documents_batch(self, batch, cursor):
        execute_values(
            cursor,
            f"INSERT INTO {self.schema}.process_documents (process_id, doc_type, document_id) VALUES %s",
            batch,
            template="(%s,%s,%s)",
            page_size=1000,
        )

    def _insert_last_movements_batch(self, batch, cursor):
        execute_values(
            cursor,
            f"""INSERT INTO {self.schema}.last_movements 
                (process_id, origin_user_id, origin_user_name, destination_user_id, 
                 destination_user_name, destination_area_name, destination_subarea_name) 
                VALUES %s""",
            batch,
            template="(%s,%s,%s,%s,%s,%s,%s)",
            page_size=1000,
        )
