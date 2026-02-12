# migrators/lml_documents.py
"""
Migrador para la colección lml_documents_mesa4core.

Implementa la interfaz BaseMigrator para transformar documentos digitales
(memos, notas, certificados, etc.) desde MongoDB al schema PostgreSQL 'lml_documents'.

RESPONSABILIDAD:
Este es un migrador de tipo 'consumer', lo que significa que:
- DEPENDE de lml_users (debe migrarse primero)
- NO inserta usuarios, solo extrae IDs y valida FKs
- Consume datos de snapshots (createdBy/updatedBy) para auditoría

ARQUITECTURA DEL SCHEMA lml_documents:
- main: Datos principales del documento
- participants: Participantes del documento
- signers: Firmantes del documento
- reviewers: Revisores del documento
- share_with: Usuarios con acceso compartido
- movements: Historial de movimientos
- recipients: Destinatarios (users, areas, subareas, groups)
- recipient_emails: Destinatarios por email
- viewers: Visualizadores
- steps: Pasos del workflow visual
- instance_privileges: Privilegios por instancia
- access: Control de acceso (whoCanAccess)
- next_workflow: Próximo usuario en workflow

CARACTERÍSTICAS:
- Campos dinámicos de formulario → JSONB dynamic_fields
- Arrays de participantes → tablas relacionales
- recipients/viewers → tablas con entity_type
- lumbreNext* → tabla unificada next_workflow
- FKs a lml_users.main para auditoría
- Manejo de "ghost users"
"""

import json
import re
from datetime import datetime, timezone
from psycopg2.extras import execute_values
from .base import BaseMigrator


class LmlDocumentsMigrator(BaseMigrator):
    """
    Migrador específico para lml_documents_mesa4core.
    """

    def __init__(self, schema="lml_documents"):
        super().__init__(schema)
        self.ghost_users_queue = []

    # =========================================================================
    # MÉTODOS PÚBLICOS (INTERFAZ REQUERIDA)
    # =========================================================================

    def get_primary_key_from_doc(self, doc):
        _id = doc.get("_id")
        if isinstance(_id, dict) and "$oid" in _id:
            return _id["$oid"]
        return str(_id)

    def initialize_batches(self):
        return {
            "main": [],
            "related": {
                "participants": [],
                "signers": [],
                "reviewers": [],
                "share_with": [],
                "movements": [],
                "recipients": [],
                "recipient_emails": [],
                "viewers": [],
                "steps": [],
                "instance_privileges": [],
                "access": [],
                "next_workflow": [],
            },
        }

    def extract_shared_entities(self, doc, cursor, caches):
        if "valid_user_ids" not in caches:
            try:
                cursor.execute("SELECT id FROM lml_users.main")
                caches["valid_user_ids"] = {row[0] for row in cursor.fetchall()}
            except Exception:
                caches["valid_user_ids"] = set()

        valid_users = caches["valid_user_ids"]

        return {
            "created_by_user_id": self._process_ghost_user(
                doc.get("createdBy"), valid_users
            ),
            "updated_by_user_id": self._process_ghost_user(
                doc.get("updatedBy"), valid_users
            ),
            "customer_id": doc.get("customerId"),
        }

    def extract_data(self, doc, shared_entities):
        document_id = self.get_primary_key_from_doc(doc)

        return {
            "main": self._extract_main_record(doc, document_id, shared_entities),
            "related": {
                "participants": self._extract_participants(doc, document_id),
                "signers": self._extract_signers(doc, document_id),
                "reviewers": self._extract_reviewers(doc, document_id),
                "share_with": self._extract_share_with(doc, document_id),
                "movements": self._extract_movements(doc, document_id),
                "recipients": self._extract_recipients(doc, document_id),
                "recipient_emails": self._extract_recipient_emails(doc, document_id),
                "viewers": self._extract_viewers(doc, document_id),
                "steps": self._extract_steps(doc, document_id),
                "instance_privileges": self._extract_instance_privileges(
                    doc, document_id
                ),
                "access": self._extract_access(doc, document_id),
                "next_workflow": self._extract_next_workflow(doc, document_id),
            },
        }

    def insert_batches(self, batches, cursor, caches=None):
        # Paso 1: Ghost users
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
                print(f"   ⚠️ Error insertando ghost users: {e}")

        # Paso 2: Main
        if batches["main"]:
            self._insert_main_batch(batches["main"], cursor)

        # Paso 3: Tablas relacionales
        if batches["related"]["participants"]:
            self._insert_participants_batch(batches["related"]["participants"], cursor)

        if batches["related"]["signers"]:
            self._insert_signers_batch(batches["related"]["signers"], cursor)

        if batches["related"]["reviewers"]:
            self._insert_reviewers_batch(batches["related"]["reviewers"], cursor)

        if batches["related"]["share_with"]:
            self._insert_share_with_batch(batches["related"]["share_with"], cursor)

        if batches["related"]["movements"]:
            self._insert_movements_batch(batches["related"]["movements"], cursor)

        if batches["related"]["recipients"]:
            self._insert_recipients_batch(batches["related"]["recipients"], cursor)

        if batches["related"]["recipient_emails"]:
            self._insert_recipient_emails_batch(
                batches["related"]["recipient_emails"], cursor
            )

        if batches["related"]["viewers"]:
            self._insert_viewers_batch(batches["related"]["viewers"], cursor)

        if batches["related"]["steps"]:
            self._insert_steps_batch(batches["related"]["steps"], cursor)

        if batches["related"]["instance_privileges"]:
            self._insert_instance_privileges_batch(
                batches["related"]["instance_privileges"], cursor
            )

        if batches["related"]["access"]:
            self._insert_access_batch(batches["related"]["access"], cursor)

        if batches["related"]["next_workflow"]:
            self._insert_next_workflow_batch(
                batches["related"]["next_workflow"], cursor
            )

    # =========================================================================
    # MÉTODOS PRIVADOS: GHOST USERS
    # =========================================================================

    def _process_ghost_user(self, snapshot, valid_users_set):
        if not snapshot or not isinstance(snapshot, dict):
            return None

        user_data = snapshot.get("user", {})
        user_id = None

        if isinstance(user_data, (str, int)):
            user_id = str(user_data)
        elif isinstance(user_data, dict):
            user_id = user_data.get("id") or user_data.get("_id")
            if isinstance(user_id, dict):
                user_id = user_id.get("$oid")

        if not user_id:
            return None
        user_id = str(user_id)

        if len(user_id) < 5:
            return None

        if user_id not in valid_users_set:
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

            self.ghost_users_queue.append(
                (user_id, firstname, lastname, email, username)
            )
            valid_users_set.add(user_id)

        return user_id

    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN - MAIN
    # =========================================================================

    def _extract_main_record(self, doc, document_id, shared_entities):
        # Identificación
        document_number = doc.get("documentNumber")
        document_name = doc.get("documentName")
        document_content = doc.get("documentContent")

        # Tipo de documento
        document_type_id = doc.get("documentTypeId")
        document_type_name = doc.get("documentTypeName")
        document_type_alias = doc.get("documentTypeAlias")
        document_type_numerator = doc.get("documentTypeNumerator")
        document_type_signature = doc.get("documentTypeSignature")
        document_type_visibility = doc.get("documentTypeVisibility")
        document_type_comunicable = doc.get("documentTypeComunicable")

        # Prefijo del tipo
        type_prefix = doc.get("documentTypePrefix", {})
        type_prefix_id = (
            type_prefix.get("id") if isinstance(type_prefix, dict) else None
        )
        type_prefix_name = (
            type_prefix.get("name") if isinstance(type_prefix, dict) else None
        )

        # Estado
        lumbre_status = doc.get("lumbreStatus", {})
        status_id = lumbre_status.get("id") if isinstance(lumbre_status, dict) else None
        status_name = (
            lumbre_status.get("name") if isinstance(lumbre_status, dict) else None
        )

        # Métricas
        lumbre_total_signers = doc.get("lumbreTotalSigners", 0)
        lumbre_total_participants = doc.get("lumbreTotalParticipants", 0)
        lumbre_total_reviewers = doc.get("lumbreTotalReviewers")
        lumbre_progress = doc.get("lumbreProgress", 0)
        lumbre_completed_signatures = doc.get("lumbreCompletedSignatures", 0)
        lumbre_completed_participants = doc.get("lumbreCompletedParticipants", 0)
        lumbre_completed_reviews = doc.get("lumbreCompletedReviews", 0)

        # Flags
        deleted = doc.get("deleted", False)
        has_external_signers = doc.get("hasExternalSigners", False)

        # PDF
        pdf_num_pages = doc.get("pdfNumPages")
        pdf_size = doc.get("pdfSize")

        # Lumbre
        lumbre_version = doc.get("lumbreVersion", 1)

        # Control de acceso (de calculatedProps)
        calculated_props = doc.get("calculatedProps", {})
        everyone_can_access = True
        if isinstance(calculated_props, dict):
            everyone_can_access = calculated_props.get("everyoneCanAccess", True)

        # Signer Reviewer
        signer_reviewer = doc.get("lumbreSignerReviewer")
        signer_reviewer_id = None
        signer_reviewer_name = None
        signer_reviewer_done = None
        if isinstance(signer_reviewer, dict) and signer_reviewer:
            signer_reviewer_id = signer_reviewer.get("id")
            signer_reviewer_name = signer_reviewer.get("name")
            signer_reviewer_done = signer_reviewer.get("done")

        # Substitute
        substitute = doc.get("lumbreSubstitute")
        substitute_id = None
        substitute_name = None
        if isinstance(substitute, dict) and substitute:
            substitute_id = substitute.get("id")
            substitute_name = substitute.get("name")

        # JSONB que se mantienen
        signer_position_map = self._to_jsonb(doc.get("signerPositionMap"))
        dynamic_fields = self._extract_dynamic_fields(doc)

        # Timestamps
        created_at = self._parse_timestamp(doc.get("createdAt"))
        updated_at = self._parse_timestamp(doc.get("updatedAt"))
        document_date = self._parse_timestamp(doc.get("documentDate"))
        last_movement_date = self._parse_timestamp(doc.get("lastMovementDate"))

        # Auditoría
        customer_id = shared_entities.get("customer_id")
        created_by_user_id = shared_entities.get("created_by_user_id")
        updated_by_user_id = shared_entities.get("updated_by_user_id")

        __v = doc.get("__v")

        return (
            document_id,
            document_number,
            document_name,
            document_content,
            document_type_id,
            document_type_name,
            document_type_alias,
            document_type_numerator,
            document_type_signature,
            document_type_visibility,
            document_type_comunicable,
            type_prefix_id,
            type_prefix_name,
            status_id,
            status_name,
            lumbre_total_signers,
            lumbre_total_participants,
            lumbre_total_reviewers,
            lumbre_progress,
            lumbre_completed_signatures,
            lumbre_completed_participants,
            lumbre_completed_reviews,
            deleted,
            has_external_signers,
            pdf_num_pages,
            pdf_size,
            lumbre_version,
            everyone_can_access,
            signer_reviewer_id,
            signer_reviewer_name,
            signer_reviewer_done,
            substitute_id,
            substitute_name,
            signer_position_map,
            dynamic_fields,
            created_at,
            updated_at,
            document_date,
            last_movement_date,
            customer_id,
            created_by_user_id,
            updated_by_user_id,
            __v,
        )

    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN - PARTICIPANTES (existentes)
    # =========================================================================

    def _extract_participants(self, doc, document_id):
        participants = doc.get("participants", [])
        records = []
        for p in participants:
            if not isinstance(p, dict):
                continue
            user_id = p.get("id")
            if user_id:
                records.append(
                    (document_id, str(user_id), p.get("name"), p.get("action"))
                )
        return records

    def _extract_signers(self, doc, document_id):
        signers = doc.get("signers", [])
        records = []
        for s in signers:
            if not isinstance(s, dict):
                continue
            user_id = s.get("id")
            if user_id:
                records.append(
                    (document_id, str(user_id), s.get("name"), s.get("action"))
                )
        return records

    def _extract_reviewers(self, doc, document_id):
        reviewers = doc.get("reviewers", [])
        records = []
        for r in reviewers:
            if not isinstance(r, dict):
                continue
            user_id = r.get("id")
            if user_id:
                records.append(
                    (document_id, str(user_id), r.get("name"), r.get("action"))
                )
        return records

    def _extract_share_with(self, doc, document_id):
        share_with = doc.get("shareWith", [])
        records = []
        for s in share_with:
            if not isinstance(s, dict):
                continue
            user_id = s.get("id")
            if user_id:
                records.append((document_id, str(user_id), s.get("name")))
        return records

    def _extract_movements(self, doc, document_id):
        movements = doc.get("movements", [])
        records = []
        for m in movements:
            if not isinstance(m, dict):
                continue
            created_at = self._parse_timestamp(m.get("created_at"))
            created_by = m.get("created_by", {})
            created_by_user_id = None
            created_by_user_name = None
            if isinstance(created_by, dict):
                created_by_user_id = created_by.get("id")
                firstname = created_by.get("firstname", "")
                lastname = created_by.get("lastname", "")
                created_by_user_name = f"{firstname} {lastname}".strip()
            movement_data = self._to_jsonb(m.get("movement"))
            documentation = self._to_jsonb(m.get("documentation"))
            records.append(
                (
                    document_id,
                    created_at,
                    created_by_user_id,
                    created_by_user_name,
                    movement_data,
                    documentation,
                )
            )
        return records

    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN - NUEVAS TABLAS
    # =========================================================================

    def _extract_recipients(self, doc, document_id):
        """Extrae recipients (users, areas, subareas, groups) a tabla unificada."""
        recipients = doc.get("recipients", {})
        if not isinstance(recipients, dict):
            return []

        records = []
        for entity_type in ["users", "areas", "subareas", "groups"]:
            items = recipients.get(entity_type, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                entity_id = item.get("id")
                if entity_id:
                    # Singularizar el tipo: users -> user, areas -> area
                    singular_type = entity_type.rstrip("s")
                    records.append(
                        (document_id, singular_type, str(entity_id), item.get("name"))
                    )
        return records

    def _extract_recipient_emails(self, doc, document_id):
        """Extrae recipients.emails a tabla separada."""
        recipients = doc.get("recipients", {})
        if not isinstance(recipients, dict):
            return []

        emails = recipients.get("emails", [])
        if not isinstance(emails, list):
            return []

        records = []
        for item in emails:
            if not isinstance(item, dict):
                continue
            email = item.get("name")  # El email está en "name"
            if email:
                records.append((document_id, item.get("id"), email))
        return records

    def _extract_viewers(self, doc, document_id):
        """Extrae viewers (users, areas, subareas) a tabla unificada."""
        viewers = doc.get("viewers", {})
        if not isinstance(viewers, dict):
            return []

        records = []
        for entity_type in ["users", "areas", "subareas"]:
            items = viewers.get(entity_type, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                entity_id = item.get("id")
                if entity_id:
                    singular_type = entity_type.rstrip("s")
                    records.append(
                        (document_id, singular_type, str(entity_id), item.get("name"))
                    )
        return records

    def _extract_steps(self, doc, document_id):
        """Extrae documentSteps.items a tabla."""
        doc_steps = doc.get("documentSteps", {})
        if not isinstance(doc_steps, dict):
            return []

        position = doc_steps.get("position", 0)
        items = doc_steps.get("items", [])
        if not isinstance(items, list) or not items:
            return []

        records = []
        for order, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            records.append(
                (
                    document_id,
                    position,
                    order,
                    item.get("title"),
                    item.get("description"),
                    item.get("avatar"),
                )
            )
        return records

    def _extract_instance_privileges(self, doc, document_id):
        """Extrae instancePrivileges (area, subarea, role) a tabla unificada."""
        privileges = doc.get("instancePrivileges", {})
        if not isinstance(privileges, dict):
            return []

        records = []
        for entity_type in ["area", "subarea", "role"]:
            items = privileges.get(entity_type, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                entity_id = item.get("id")
                if entity_id:
                    records.append(
                        (document_id, entity_type, str(entity_id), item.get("name"))
                    )
        return records

    def _extract_access(self, doc, document_id):
        """Extrae calculatedProps.whoCanAccess a tabla."""
        calculated_props = doc.get("calculatedProps", {})
        if not isinstance(calculated_props, dict):
            return []

        who_can_access = calculated_props.get("whoCanAccess", {})
        if not isinstance(who_can_access, dict):
            return []

        records = []
        for entity_type in ["users", "areas", "subareas"]:
            items = who_can_access.get(entity_type, [])
            if not isinstance(items, list):
                continue
            for entity_id in items:
                if entity_id:
                    singular_type = entity_type.rstrip("s")
                    records.append((document_id, singular_type, str(entity_id)))
        return records

    def _extract_next_workflow(self, doc, document_id):
        """Extrae lumbreNextSigner/Participant/Reviewer a tabla unificada."""
        records = []

        workflow_fields = [
            ("signer", "lumbreNextSigner"),
            ("participant", "lumbreNextParticipant"),
            ("reviewer", "lumbreNextReviewer"),
        ]

        for workflow_type, field_name in workflow_fields:
            data = doc.get(field_name)
            if not isinstance(data, dict) or not data:
                continue

            # Extraer datos del usuario
            user_id = data.get("id") or data.get("_id")
            if isinstance(user_id, dict):
                user_id = user_id.get("$oid")

            if not user_id:
                continue

            # Extraer rol
            role = data.get("role", {})
            role_id = role.get("id") if isinstance(role, dict) else None
            role_name = role.get("name") if isinstance(role, dict) else None

            # Extraer área
            area = data.get("area", {})
            area_id = area.get("id") if isinstance(area, dict) else None
            area_name = area.get("name") if isinstance(area, dict) else None

            # Extraer subárea
            subarea = data.get("subarea", {})
            subarea_id = subarea.get("id") if isinstance(subarea, dict) else None
            subarea_name = subarea.get("name") if isinstance(subarea, dict) else None

            # Extraer posición (opcional)
            position = data.get("position", {})
            position_id = position.get("id") if isinstance(position, dict) else None
            position_name = position.get("name") if isinstance(position, dict) else None

            # Extraer reviewer embebido (si existe)
            reviewer = data.get("reviewer", {})
            reviewer_id = reviewer.get("id") if isinstance(reviewer, dict) else None
            reviewer_name = reviewer.get("name") if isinstance(reviewer, dict) else None

            records.append(
                (
                    document_id,
                    workflow_type,
                    str(user_id),
                    data.get("firstname"),
                    data.get("lastname"),
                    data.get("email"),
                    data.get("userType"),
                    data.get("userInitials"),
                    data.get("profilePicture"),
                    role_id,
                    role_name,
                    area_id,
                    area_name,
                    subarea_id,
                    subarea_name,
                    position_id,
                    position_name,
                    data.get("action"),
                    data.get("signature"),
                    data.get("inCharacterOf"),
                    reviewer_id,
                    reviewer_name,
                )
            )

        return records

    # =========================================================================
    # MÉTODOS PRIVADOS: HELPERS
    # =========================================================================

    def _extract_dynamic_fields(self, doc):
        dynamic_fields = {}
        dynamic_pattern = re.compile(r"^(.+_\d+|_\d+)$")
        known_fields = {"_id", "__v", "_v", "_master", "_masterType"}

        for key, value in doc.items():
            if key in known_fields:
                continue
            if dynamic_pattern.match(key):
                if value is not None and value != "" and value != []:
                    dynamic_fields[key] = value

        if dynamic_fields:
            return json.dumps(dynamic_fields, ensure_ascii=False, default=str)
        return None

    def _to_jsonb(self, value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return None

    def _parse_timestamp(self, value):
        if not value:
            return None
        try:
            if isinstance(value, datetime):
                return value
            if isinstance(value, dict) and "$date" in value:
                value = value["$date"]
            if isinstance(value, str):
                if value.endswith("Z"):
                    if "." in value:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
                    else:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                if "+" in value or value.count("-") > 2:
                    return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
        return None

    # =========================================================================
    # MÉTODOS PRIVADOS: INSERCIÓN
    # =========================================================================

    def _insert_main_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.main (
                document_id, document_number, document_name, document_content,
                document_type_id, document_type_name, document_type_alias,
                document_type_numerator, document_type_signature, document_type_visibility,
                document_type_comunicable, type_prefix_id, type_prefix_name,
                status_id, status_name,
                lumbre_total_signers, lumbre_total_participants, lumbre_total_reviewers,
                lumbre_progress, lumbre_completed_signatures, lumbre_completed_participants,
                lumbre_completed_reviews, deleted, has_external_signers,
                pdf_num_pages, pdf_size, lumbre_version,
                everyone_can_access, signer_reviewer_id, signer_reviewer_name,
                signer_reviewer_done, substitute_id, substitute_name,
                signer_position_map, dynamic_fields,
                created_at, updated_at, document_date, last_movement_date,
                customer_id, created_by_user_id, updated_by_user_id, __v
            ) VALUES %s
            ON CONFLICT (document_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=500,
        )

    def _insert_participants_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.participants (document_id, user_id, user_name, action)
            VALUES %s ON CONFLICT (document_id, user_id, action) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_signers_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.signers (document_id, user_id, user_name, action)
            VALUES %s ON CONFLICT (document_id, user_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_reviewers_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.reviewers (document_id, user_id, user_name, action)
            VALUES %s ON CONFLICT (document_id, user_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_share_with_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.share_with (document_id, user_id, user_name)
            VALUES %s ON CONFLICT (document_id, user_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s)",
            page_size=1000,
        )

    def _insert_movements_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.movements (
                document_id, created_at, created_by_user_id,
                created_by_user_name, movement_data, documentation
            ) VALUES %s
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_recipients_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.recipients (document_id, entity_type, entity_id, entity_name)
            VALUES %s ON CONFLICT (document_id, entity_type, entity_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_recipient_emails_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.recipient_emails (document_id, email_id, email)
            VALUES %s ON CONFLICT (document_id, email) DO NOTHING
            """,
            records,
            template="(%s, %s, %s)",
            page_size=1000,
        )

    def _insert_viewers_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.viewers (document_id, entity_type, entity_id, entity_name)
            VALUES %s ON CONFLICT (document_id, entity_type, entity_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_steps_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.steps (document_id, position, step_order, title, description, avatar)
            VALUES %s
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_instance_privileges_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.instance_privileges (document_id, entity_type, entity_id, entity_name)
            VALUES %s ON CONFLICT (document_id, entity_type, entity_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_access_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.access (document_id, entity_type, entity_id)
            VALUES %s ON CONFLICT (document_id, entity_type, entity_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s)",
            page_size=1000,
        )

    def _insert_next_workflow_batch(self, records, cursor):
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.next_workflow (
                document_id, workflow_type, user_id, firstname, lastname, email,
                user_type, user_initials, profile_picture,
                role_id, role_name, area_id, area_name, subarea_id, subarea_name,
                position_id, position_name, action, signature, in_character_of,
                reviewer_id, reviewer_name
            ) VALUES %s ON CONFLICT (document_id, workflow_type) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=1000,
        )
