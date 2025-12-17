# migrators/lml_processtypes.py
"""
Migrador para la colección lml_processtypes_mesa4core.

Implementa la interfaz BaseMigrator para transformar documentos de tipos
de trámites desde MongoDB al schema PostgreSQL 'lml_processtypes'.

RESPONSABILIDAD:
Este es un migrador de tipo 'consumer', lo que significa que:
- DEPENDE de lml_users (roles, areas, subareas)
- DEPENDE de lml_listbuilder y lml_formbuilder (referencias)
- NO inserta en lml_users, solo referencia vía FK

TABLAS DESTINO:
- main: Configuración principal del tipo de trámite
- process_fields: Campos del formulario (1:N)
- type_prefixes: Catálogo de prefijos (propio)
- people_types: Catálogo de tipos de persona (propio)
- initiator_types: Catálogo de tipos de iniciador (propio)
- starter_people_types: Relación N:M con people_types
- starter_initiator_types: Relación N:M con initiator_types
- instance_actions_area: Áreas con permisos (FK a lml_users.areas)
- instance_actions_subarea: Subáreas con permisos (FK a lml_users.subareas)
- instance_actions_edit_area: Áreas con permisos de edición
- instance_actions_edit_subarea: Subáreas con permisos de edición
- instance_actions_edit_role: Roles con permisos de edición (FK a lml_users.roles)

FOREIGN KEYS A lml_users:
- type_correction_role_id → lml_users.roles(id)
- type_reopen_role_id → lml_users.roles(id)
- instance_actions_*.area_id → lml_users.areas(id)
- instance_actions_*.subarea_id → lml_users.subareas(id)
- instance_actions_edit_role.role_id → lml_users.roles(id)
"""

import json
from psycopg2.extras import execute_values
from .base import BaseMigrator
from datetime import datetime


class LmlProcesstypesMigrator(BaseMigrator):
    """
    Migrador específico para lml_processtypes_mesa4core.

    Transforma configuraciones de tipos de trámites desde MongoDB
    a un modelo relacional normalizado en PostgreSQL.
    """

    def __init__(self, schema="lml_processtypes"):
        """
        Constructor del migrador.

        Args:
            schema: Nombre del schema destino en PostgreSQL
        """
        super().__init__(schema)
        self.ghost_users_queue = []

    # =========================================================================
    # MÉTODOS PÚBLICOS - INTERFAZ BaseMigrator
    # =========================================================================

    def get_primary_key_from_doc(self, doc):
        """Extrae el ID del documento MongoDB."""
        _id = doc.get("_id")
        if isinstance(_id, dict) and "$oid" in _id:
            return _id["$oid"]
        return str(_id)

    def initialize_batches(self):
        """Retorna estructura vacía para acumular batches."""
        return {
            "main": [],
            "related": {
                # Catálogos propios
                "type_prefixes": [],
                "people_types": [],
                "initiator_types": [],
                # Relaciones con starters
                "starter_people_types": [],
                "starter_initiator_types": [],
                # Instance actions
                "instance_actions_area": [],
                "instance_actions_subarea": [],
                # Instance actions edit
                "instance_actions_edit_area": [],
                "instance_actions_edit_subarea": [],
                "instance_actions_edit_role": [],
                # Process fields
                "process_fields": [],
            },
        }

    def extract_shared_entities(self, doc, cursor, caches):
        """
        Extrae IDs de usuarios y valida existencia de roles/areas/subareas.
        """
        # Cargar caché de usuarios
        if "valid_user_ids" not in caches:
            try:
                cursor.execute("SELECT id FROM lml_users.main")
                caches["valid_user_ids"] = {row[0] for row in cursor.fetchall()}
            except Exception:
                caches["valid_user_ids"] = set()

        # Cargar caché de roles (para typeCorrection y typeReOpen)
        if "valid_role_ids" not in caches:
            try:
                cursor.execute("SELECT id FROM lml_users.roles")
                caches["valid_role_ids"] = {row[0] for row in cursor.fetchall()}
            except Exception:
                caches["valid_role_ids"] = set()

        # Cargar caché de áreas
        if "valid_area_ids" not in caches:
            try:
                cursor.execute("SELECT id FROM lml_users.areas")
                caches["valid_area_ids"] = {row[0] for row in cursor.fetchall()}
            except Exception:
                caches["valid_area_ids"] = set()

        # Cargar caché de subáreas
        if "valid_subarea_ids" not in caches:
            try:
                cursor.execute("SELECT id FROM lml_users.subareas")
                caches["valid_subarea_ids"] = {row[0] for row in cursor.fetchall()}
            except Exception:
                caches["valid_subarea_ids"] = set()

        valid_users = caches["valid_user_ids"]

        # Extraer IDs de typeCorrection y typeReOpen (son roles)
        type_correction = doc.get("typeCorrection", {})
        type_reopen = doc.get("typeReOpen", {})

        return {
            "created_by_user_id": self._process_ghost_user(
                doc.get("createdBy"), valid_users
            ),
            "updated_by_user_id": self._process_ghost_user(
                doc.get("updatedBy"), valid_users
            ),
            "customer_id": doc.get("customerId"),
            "type_correction_role_id": (
                type_correction.get("id") if isinstance(type_correction, dict) else None
            ),
            "type_reopen_role_id": (
                type_reopen.get("id") if isinstance(type_reopen, dict) else None
            ),
            "valid_role_ids": caches["valid_role_ids"],
            "valid_area_ids": caches["valid_area_ids"],
            "valid_subarea_ids": caches["valid_subarea_ids"],
        }

    def extract_data(self, doc, shared_entities):
        """Extrae datos del documento para insertar en PostgreSQL."""
        processtype_id = self.get_primary_key_from_doc(doc)

        # Extraer catálogos propios
        type_prefixes = self._extract_type_prefix(doc)
        people_types, starter_people = self._extract_people_types(doc, processtype_id)
        initiator_types, starter_initiators = self._extract_initiator_types(
            doc, processtype_id
        )

        # Extraer instance actions
        actions_area, actions_subarea = self._extract_instance_actions(
            doc, processtype_id, shared_entities
        )

        # Extraer instance actions edit
        edit_area, edit_subarea, edit_role = self._extract_instance_actions_edit(
            doc, processtype_id, shared_entities
        )

        return {
            "main": self._extract_main_record(doc, processtype_id, shared_entities),
            "related": {
                "type_prefixes": type_prefixes,
                "people_types": people_types,
                "initiator_types": initiator_types,
                "starter_people_types": starter_people,
                "starter_initiator_types": starter_initiators,
                "instance_actions_area": actions_area,
                "instance_actions_subarea": actions_subarea,
                "instance_actions_edit_area": edit_area,
                "instance_actions_edit_subarea": edit_subarea,
                "instance_actions_edit_role": edit_role,
                "process_fields": self._extract_process_fields(doc, processtype_id),
            },
        }

    def insert_batches(self, batches, cursor, caches=None):
        """Inserta los batches acumulados en PostgreSQL."""

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

        # Paso 2: Catálogos propios (deben existir antes de main por FKs)
        if batches["related"]["type_prefixes"]:
            self._insert_type_prefixes_batch(
                batches["related"]["type_prefixes"], cursor
            )

        if batches["related"]["people_types"]:
            self._insert_people_types_batch(batches["related"]["people_types"], cursor)

        if batches["related"]["initiator_types"]:
            self._insert_initiator_types_batch(
                batches["related"]["initiator_types"], cursor
            )

        # Paso 3: Tabla main
        if batches["main"]:
            self._insert_main_batch(batches["main"], cursor)

        # Paso 4: Tablas relacionales (requieren main por FK)
        if batches["related"]["starter_people_types"]:
            self._insert_starter_people_types_batch(
                batches["related"]["starter_people_types"], cursor
            )

        if batches["related"]["starter_initiator_types"]:
            self._insert_starter_initiator_types_batch(
                batches["related"]["starter_initiator_types"], cursor
            )

        if batches["related"]["instance_actions_area"]:
            self._insert_instance_actions_area_batch(
                batches["related"]["instance_actions_area"], cursor
            )

        if batches["related"]["instance_actions_subarea"]:
            self._insert_instance_actions_subarea_batch(
                batches["related"]["instance_actions_subarea"], cursor
            )

        if batches["related"]["instance_actions_edit_area"]:
            self._insert_instance_actions_edit_area_batch(
                batches["related"]["instance_actions_edit_area"], cursor
            )

        if batches["related"]["instance_actions_edit_subarea"]:
            self._insert_instance_actions_edit_subarea_batch(
                batches["related"]["instance_actions_edit_subarea"], cursor
            )

        if batches["related"]["instance_actions_edit_role"]:
            self._insert_instance_actions_edit_role_batch(
                batches["related"]["instance_actions_edit_role"], cursor
            )

        if batches["related"]["process_fields"]:
            self._insert_process_fields_batch(
                batches["related"]["process_fields"], cursor
            )

    # =========================================================================
    # MÉTODOS PRIVADOS - EXTRACCIÓN DE DATOS
    # =========================================================================

    def _process_ghost_user(self, snapshot, valid_users_set):
        """Procesa snapshot de usuario, agregando a cola de fantasmas si no existe."""
        if not snapshot or not isinstance(snapshot, dict):
            return None

        user = snapshot.get("user")
        if not user or not isinstance(user, dict):
            return None

        user_id = user.get("id")
        if not user_id:
            return None

        if user_id in valid_users_set:
            return user_id

        ghost_data = (
            user_id,
            user.get("firstname", "Ghost"),
            user.get("lastname", "User"),
            user.get("email", f"{user_id}@ghost.local"),
            user.get("username"),
        )

        existing_ids = {g[0] for g in self.ghost_users_queue}
        if user_id not in existing_ids:
            self.ghost_users_queue.append(ghost_data)
            valid_users_set.add(user_id)

        return user_id

    def _extract_type_prefix(self, doc):
        """Extrae typePrefix como registro de catálogo."""
        prefix = doc.get("typePrefix")
        if prefix and isinstance(prefix, dict) and prefix.get("id"):
            return [(prefix["id"], prefix.get("name", ""))]
        return []

    def _extract_people_types(self, doc, processtype_id):
        """Extrae peopleTypes: catálogo y relación."""
        starters = doc.get("instanceStarters", {})
        people_types = starters.get("peopleTypes", [])

        catalog = []
        relations = []

        for pt in people_types:
            if isinstance(pt, dict) and pt.get("id"):
                catalog.append((pt["id"], pt.get("name", "")))
                relations.append((processtype_id, pt["id"]))

        return catalog, relations

    def _extract_initiator_types(self, doc, processtype_id):
        """Extrae initiatorTypes: catálogo y relación."""
        starters = doc.get("instanceStarters", {})
        initiator_types = starters.get("initiatorTypes", [])

        catalog = []
        relations = []

        for it in initiator_types:
            if isinstance(it, dict) and it.get("id"):
                catalog.append((it["id"], it.get("name", "")))
                relations.append((processtype_id, it["id"]))

        return catalog, relations

    def _extract_instance_actions(self, doc, processtype_id, shared_entities):
        """Extrae instanceActions (area y subarea con permisos)."""
        actions = doc.get("instanceActions", {})
        valid_areas = shared_entities.get("valid_area_ids", set())
        valid_subareas = shared_entities.get("valid_subarea_ids", set())
        valid_roles = shared_entities.get("valid_role_ids", set())

        area_records = []
        subarea_records = []

        # Áreas
        for item in actions.get("area", []):
            if isinstance(item, dict) and item.get("id"):
                area_id = item["id"]
                role_obj = item.get("role")
                role_id = role_obj.get("id") if isinstance(role_obj, dict) else None

                # Validar FK (solo insertar si area existe en lml_users)
                if area_id in valid_areas:
                    area_records.append(
                        (
                            processtype_id,
                            area_id,
                            item.get("name"),
                            role_id if role_id in valid_roles else None,
                            item.get("action"),
                        )
                    )

        # Subáreas
        for item in actions.get("subarea", []):
            if isinstance(item, dict) and item.get("id"):
                subarea_id = item["id"]
                role_obj = item.get("role")
                role_id = role_obj.get("id") if isinstance(role_obj, dict) else None

                if subarea_id in valid_subareas:
                    subarea_records.append(
                        (
                            processtype_id,
                            subarea_id,
                            item.get("name"),
                            role_id if role_id in valid_roles else None,
                            item.get("action"),
                        )
                    )

        return area_records, subarea_records

    def _extract_instance_actions_edit(self, doc, processtype_id, shared_entities):
        """Extrae instanceActionsEdit (area, subarea, role con permisos de edición)."""
        actions = doc.get("instanceActionsEdit", {})
        valid_areas = shared_entities.get("valid_area_ids", set())
        valid_subareas = shared_entities.get("valid_subarea_ids", set())
        valid_roles = shared_entities.get("valid_role_ids", set())

        area_records = []
        subarea_records = []
        role_records = []

        # Áreas
        for item in actions.get("area", []):
            if isinstance(item, dict) and item.get("id"):
                area_id = item["id"]
                if area_id in valid_areas:
                    area_records.append((processtype_id, area_id, item.get("name")))

        # Subáreas
        for item in actions.get("subarea", []):
            if isinstance(item, dict) and item.get("id"):
                subarea_id = item["id"]
                if subarea_id in valid_subareas:
                    subarea_records.append(
                        (processtype_id, subarea_id, item.get("name"))
                    )

        # Roles
        for item in actions.get("role", []):
            if isinstance(item, dict) and item.get("id"):
                role_id = item["id"]
                if role_id in valid_roles:
                    role_records.append((processtype_id, role_id, item.get("name")))

        return area_records, subarea_records, role_records

    def _extract_main_record(self, doc, processtype_id, shared_entities):
        """Extrae tupla para lml_processtypes.main."""
        # Extraer prefix_id
        prefix = doc.get("typePrefix", {})
        prefix_id = prefix.get("id") if isinstance(prefix, dict) else None

        return (
            processtype_id,
            doc.get("typeName"),
            doc.get("typeAlias"),
            doc.get("typeDescription"),
            doc.get("typeNumerator"),
            doc.get("typeComments"),
            doc.get("typeCanBeTaken"),
            doc.get("typeCanBeTakenDetail"),
            doc.get("typeHideCommentsOnFinished"),
            doc.get("tadAvailable"),
            doc.get("tadUrl"),
            doc.get("isEditable"),
            doc.get("published"),
            doc.get("deleted"),
            doc.get("userWhoAssociatedCanCorrect"),
            doc.get("lumbreVersion"),
            doc.get("_master"),
            doc.get("__v"),
            doc.get("_v"),
            doc.get("listbuilderId"),
            doc.get("formbuilderId"),
            shared_entities["customer_id"],
            prefix_id,
            shared_entities["type_correction_role_id"],
            shared_entities["type_reopen_role_id"],
            # JSONB fields
            (
                json.dumps(doc.get("calculatedProps"))
                if doc.get("calculatedProps")
                else None
            ),
            (
                json.dumps(doc.get("contenttemplateConditionals"))
                if doc.get("contenttemplateConditionals")
                else None
            ),
            (
                json.dumps(doc.get("processFieldsValidations"))
                if doc.get("processFieldsValidations")
                else None
            ),
            json.dumps(doc.get("suggest")) if doc.get("suggest") else None,
            # Auditoría
            shared_entities["created_by_user_id"],
            shared_entities["updated_by_user_id"],
            self._parse_timestamp(doc.get("createdAt")),
            self._parse_timestamp(doc.get("updatedAt")),
        )

    def _extract_process_fields(self, doc, processtype_id):
        """Extrae registros para lml_processtypes.process_fields."""
        fields = doc.get("processFields", [])
        records = []

        for order, field in enumerate(fields):
            if not isinstance(field, dict):
                continue

            field_id = field.get("id")
            if field_id is not None:
                field_id = str(field_id)

            records.append(
                (
                    processtype_id,
                    field_id,
                    order,
                    field.get("class"),
                    field.get("componentName"),
                    field.get("formObjectToSendToServerProperty"),
                    field.get("isHiddenOnPdf"),
                    field.get("hasLabelOnPdf"),
                    (
                        json.dumps(field.get("componentProps"))
                        if field.get("componentProps")
                        else None
                    ),
                    (
                        json.dumps(field.get("componentPermissions"))
                        if field.get("componentPermissions")
                        else None
                    ),
                    (
                        json.dumps(field.get("visibilityDependOnConditions"))
                        if field.get("visibilityDependOnConditions")
                        else None
                    ),
                )
            )

        return records

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

    # =========================================================================
    # MÉTODOS PRIVADOS - INSERCIÓN EN POSTGRESQL
    # =========================================================================

    def _insert_type_prefixes_batch(self, records, cursor):
        """Inserta catálogo de prefijos."""
        unique = list({r[0]: r for r in records}.values())
        execute_values(
            cursor,
            f"INSERT INTO {self.schema}.type_prefixes (id, name) VALUES %s ON CONFLICT (id) DO NOTHING",
            unique,
            template="(%s, %s)",
            page_size=500,
        )

    def _insert_people_types_batch(self, records, cursor):
        """Inserta catálogo de tipos de persona."""
        unique = list({r[0]: r for r in records}.values())
        execute_values(
            cursor,
            f"INSERT INTO {self.schema}.people_types (id, name) VALUES %s ON CONFLICT (id) DO NOTHING",
            unique,
            template="(%s, %s)",
            page_size=500,
        )

    def _insert_initiator_types_batch(self, records, cursor):
        """Inserta catálogo de tipos de iniciador."""
        unique = list({r[0]: r for r in records}.values())
        execute_values(
            cursor,
            f"INSERT INTO {self.schema}.initiator_types (id, name) VALUES %s ON CONFLICT (id) DO NOTHING",
            unique,
            template="(%s, %s)",
            page_size=500,
        )

    def _insert_main_batch(self, records, cursor):
        """Inserta batch en lml_processtypes.main."""
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.main (
                processtype_id, type_name, type_alias, type_description,
                type_numerator, type_comments, type_can_be_taken, type_can_be_taken_detail,
                type_hide_comments_on_finished, tad_available, tad_url,
                is_editable, published, deleted, user_who_associated_can_correct,
                lumbre_version, _master, __v, _v,
                listbuilder_id, formbuilder_id, customer_id,
                type_prefix_id, type_correction_role_id, type_reopen_role_id,
                calculated_props, contenttemplate_conditionals, process_fields_validations, suggest,
                created_by_user_id, updated_by_user_id, created_at, updated_at
            ) VALUES %s
            ON CONFLICT (processtype_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=500,
        )

    def _insert_starter_people_types_batch(self, records, cursor):
        """Inserta relaciones processtype ↔ people_type."""
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.starter_people_types (processtype_id, people_type_id) 
            VALUES %s ON CONFLICT (processtype_id, people_type_id) DO NOTHING
            """,
            records,
            template="(%s, %s)",
            page_size=1000,
        )

    def _insert_starter_initiator_types_batch(self, records, cursor):
        """Inserta relaciones processtype ↔ initiator_type."""
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.starter_initiator_types (processtype_id, initiator_type_id) 
            VALUES %s ON CONFLICT (processtype_id, initiator_type_id) DO NOTHING
            """,
            records,
            template="(%s, %s)",
            page_size=1000,
        )

    def _insert_instance_actions_area_batch(self, records, cursor):
        """Inserta áreas con permisos de acción."""
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.instance_actions_area 
            (processtype_id, area_id, area_name, role_id, action) 
            VALUES %s ON CONFLICT (processtype_id, area_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_instance_actions_subarea_batch(self, records, cursor):
        """Inserta subáreas con permisos de acción."""
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.instance_actions_subarea 
            (processtype_id, subarea_id, subarea_name, role_id, action) 
            VALUES %s ON CONFLICT (processtype_id, subarea_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s, %s)",
            page_size=1000,
        )

    def _insert_instance_actions_edit_area_batch(self, records, cursor):
        """Inserta áreas con permisos de edición."""
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.instance_actions_edit_area 
            (processtype_id, area_id, area_name) 
            VALUES %s ON CONFLICT (processtype_id, area_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s)",
            page_size=1000,
        )

    def _insert_instance_actions_edit_subarea_batch(self, records, cursor):
        """Inserta subáreas con permisos de edición."""
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.instance_actions_edit_subarea 
            (processtype_id, subarea_id, subarea_name) 
            VALUES %s ON CONFLICT (processtype_id, subarea_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s)",
            page_size=1000,
        )

    def _insert_instance_actions_edit_role_batch(self, records, cursor):
        """Inserta roles con permisos de edición."""
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.instance_actions_edit_role 
            (processtype_id, role_id, role_name) 
            VALUES %s ON CONFLICT (processtype_id, role_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s)",
            page_size=1000,
        )

    def _insert_process_fields_batch(self, records, cursor):
        """Inserta campos del formulario."""
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.process_fields (
                processtype_id, field_id, field_order,
                class, component_name, form_property,
                is_hidden_on_pdf, has_label_on_pdf,
                component_props, component_permissions, visibility_conditions
            ) VALUES %s
            ON CONFLICT (processtype_id, field_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=1000,
        )
