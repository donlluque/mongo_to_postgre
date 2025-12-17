# migrators/lml_people.py
"""
Migrador para la colección lml_people_mesa4core.

Implementa la interfaz BaseMigrator para transformar documentos de personas
(físicas y jurídicas) desde MongoDB al schema PostgreSQL 'lml_people'.

RESPONSABILIDAD:
Este es un migrador de tipo 'consumer', lo que significa que:
- DEPENDE de lml_users (debe migrarse primero)
- NO inserta usuarios, solo extrae IDs y valida FKs
- Consume datos de snapshots (createdBy/updatedBy) para auditoría

ARQUITECTURA DEL SCHEMA lml_people:
- main: Datos principales de personas (campos específicos por tipo)
- people_types: Catálogo de tipos (Humana v2, Jurídica v2)
- person_id_types: Catálogo de tipos de documento (DNI, CUIL, CUIT)

CARACTERÍSTICAS:
- Dos tipos de persona: Humana (88.5%) y Jurídica (11.5%)
- Campos específicos por tipo como columnas nullable
- dynamic_fields JSONB para campos _3, _4, _5, _6, _7
- FKs a lml_users.main para auditoría
- Manejo de "ghost users" (usuarios no migrados pero referenciados)

Uso (desde mongomigra.py):
    migrator = LmlPeopleMigrator(schema='lml_people')

    shared = migrator.extract_shared_entities(doc, cursor, caches)
    data = migrator.extract_data(doc, shared)

    # Acumular en batches...
    migrator.insert_batches(batches, cursor)
"""

import json
from datetime import datetime
from psycopg2.extras import execute_values
from .base import BaseMigrator
from datetime import datetime, timezone


class LmlPeopleMigrator(BaseMigrator):
    """
    Migrador específico para lml_people_mesa4core.

    Transforma documentos de personas con catálogos embebidos y campos
    dinámicos desde MongoDB a un modelo relacional normalizado en PostgreSQL.

    Tablas destino:
    - {schema}.main: Datos principales de la persona
    - {schema}.people_types: Catálogo de tipos de persona
    - {schema}.person_id_types: Catálogo de tipos de documento

    Attributes:
        schema (str): Nombre del schema en PostgreSQL ('lml_people')
        ghost_users_queue (list): Cola de usuarios faltantes para insertar en lote
    """

    def __init__(self, schema="lml_people"):
        """
        Constructor del migrador.

        Args:
            schema: Nombre del schema destino en PostgreSQL
        """
        super().__init__(schema)
        # Cola en memoria para acumular usuarios fantasmas antes de insertar en lote
        self.ghost_users_queue = []

    # =========================================================================
    # MÉTODOS PÚBLICOS (INTERFAZ REQUERIDA)
    # =========================================================================

    def get_primary_key_from_doc(self, doc):
        """
        Extrae el people_id desde el documento MongoDB.

        Implementa interfaz de BaseMigrator.

        Args:
            doc: Documento MongoDB (dict)

        Returns:
            str: El _id convertido a string
        """
        _id = doc.get("_id")
        if isinstance(_id, dict) and "$oid" in _id:
            return _id["$oid"]
        return str(_id)

    def initialize_batches(self):
        """
        Retorna estructura vacía para acumular batches.

        Implementa interfaz de BaseMigrator.

        La estructura refleja las tablas destino:
        - main: Tuplas para lml_people.main
        - related: Dict con arrays para catálogos embebidos

        Returns:
            dict: Estructura de batches vacía
        """
        return {"main": [], "related": {"people_types": [], "person_id_types": []}}

    def extract_shared_entities(self, doc, cursor, caches):
        """
        Extrae IDs de usuarios. Si falta un usuario, lo guarda en memoria
        (cola) para insertarlo después.

        Implementa interfaz de BaseMigrator.

        Args:
            doc: Documento MongoDB
            cursor: Cursor de psycopg2
            caches: Dict de sets para caché en memoria

        Returns:
            dict: IDs extraídos {
                'created_by_user_id': str,
                'updated_by_user_id': str,
                'customer_id': str
            }
        """
        # A. Cargar caché inicial de usuarios (Solo la primera vez)
        if "valid_user_ids" not in caches:
            try:
                cursor.execute("SELECT id FROM lml_users.main")
                caches["valid_user_ids"] = {row[0] for row in cursor.fetchall()}
            except Exception:
                caches["valid_user_ids"] = set()

        valid_users = caches["valid_user_ids"]

        # B. Procesar createdBy/updatedBy usando lógica de ghost users
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
        """
        Extrae todos los datos del documento en estructura normalizada.

        Implementa interfaz de BaseMigrator.

        Proceso:
        1. Extraer catálogos embebidos (people_type, person_id_type)
        2. Extraer datos de la persona principal
        3. Normalizar campos dinámicos a JSONB
        4. Manejar campos específicos por tipo (humana vs jurídica)

        Args:
            doc: Documento MongoDB completo
            shared_entities: Dict con IDs de entidades compartidas (del método anterior)

        Returns:
            dict: Estructura {
                'main': tupla para tabla main,
                'related': {
                    'people_types': [tupla],
                    'person_id_types': [tupla]
                }
            }
        """
        people_id = self.get_primary_key_from_doc(doc)

        # Extraer catálogos embebidos
        people_type = self._extract_people_type(doc)
        person_id_type = self._extract_person_id_type(doc)

        return {
            "main": self._extract_main_record(doc, shared_entities),
            "related": {
                "people_types": [people_type] if people_type else [],
                "person_id_types": [person_id_type] if person_id_type else [],
            },
        }

    def insert_batches(self, batches, cursor, caches=None):
        """
        Inserta todos los batches acumulados en PostgreSQL.

        Implementa interfaz de BaseMigrator.

        ORDEN CRÍTICO:
        1. Usuarios fantasmas (si hay pendientes)
        2. Catálogos embebidos (people_types, person_id_types)
        3. Tabla main (personas)

        Justificación: lml_people.main tiene FKs a catálogos y usuarios,
        deben existir primero.

        Args:
            batches: Dict con estructura de initialize_batches()
            cursor: Cursor de psycopg2
            caches: Dict de sets para actualizar caché
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

                # Actualizar caché con usuarios recién insertados
                if caches and "valid_user_ids" in caches:
                    caches["valid_user_ids"].update(
                        [u[0] for u in self.ghost_users_queue]
                    )

                self.ghost_users_queue = []
            except Exception as e:
                print(f"   ❌ Error insertando lote de ghost users: {e}")

        # --- Inserción Normal con execute_values ---
        # Insertar catálogos embebidos primero (con UPSERT)
        if batches["related"]["people_types"]:
            self._insert_people_types_batch(batches["related"]["people_types"], cursor)

        if batches["related"]["person_id_types"]:
            self._insert_person_id_types_batch(
                batches["related"]["person_id_types"], cursor
            )

        # Insertar tabla main
        if batches["main"]:
            self._insert_main_batch(batches["main"], cursor)

    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN DE IDS (GHOST USERS)
    # =========================================================================

    def _process_ghost_user(self, snapshot, valid_users_set):
        """
        Verifica si el usuario existe. Si no, extrae sus datos y lo agrega
        a la cola de espera.

        Este método implementa la lógica de "ghost users": usuarios que
        fueron referenciados en snapshots pero no existen en lml_users.main.

        Args:
            snapshot: Dict con estructura {user: {id, firstname, ...}, userAgent, userIp}
            valid_users_set: Set con IDs de usuarios existentes en lml_users.main

        Returns:
            str | None: user_id si es válido, None si no se pudo extraer
        """
        if not snapshot or not isinstance(snapshot, dict):
            return None

        user_data = snapshot.get("user", {})
        user_id = None

        # --- Extracción del ID ---
        if isinstance(user_data, (str, int)):
            user_id = str(user_data)
        elif isinstance(user_data, dict):
            user_id = user_data.get("id") or user_data.get("_id")
            if isinstance(user_id, dict):
                user_id = user_id.get("$oid")

        if not user_id:
            return None

        user_id = str(user_id)

        # Filtro de basura (IDs muy cortos no sirven)
        if len(user_id) < 5:
            return None

        # --- LÓGICA CORE: COMPARACIÓN EN MEMORIA ---
        # Si NO está en el set de usuarios válidos, es un fantasma nuevo
        if user_id not in valid_users_set:

            # Preparamos los datos para restaurarlo
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

            # 1. Agregamos a la COLA para insertar luego todos juntos
            # NOTA: Marcamos deleted=TRUE para diferenciarlo
            self.ghost_users_queue.append(
                (user_id, firstname, lastname, email, username)
            )

            # 2. Agregamos al SET inmediatamente para no duplicarlo en el mismo lote
            valid_users_set.add(user_id)

        return user_id

    # =========================================================================
    # MÉTODOS PRIVADOS: EXTRACCIÓN DE DATOS
    # =========================================================================

    def _extract_main_record(self, doc, shared_entities):
        """
        Extrae el registro principal para lml_people.main.

        Maneja:
        - Campos comunes (person_name, person_email, person_id)
        - Campos específicos de Humana (domicilio_*, piso_*, departamento_*)
        - Campos específicos de Jurídica (tipo_*, direccion_*)
        - Campos dinámicos → JSONB
        - Timestamps (conversión de múltiples formatos)
        - FKs a catálogos y usuarios

        Args:
            doc: Documento MongoDB
            shared_entities: Dict con IDs extraídos (created_by_user_id, etc.)

        Returns:
            tuple: Tupla con valores para INSERT en lml_people.main
        """
        people_id = self.get_primary_key_from_doc(doc)

        # Referencias a catálogos propios
        people_type_id = doc.get("peopleTypeId")

        # Extraer person_id_type_id del objeto embebido
        person_id_type = doc.get("personIdType", {})
        person_id_type_id = None
        if isinstance(person_id_type, dict):
            person_id_type_id = person_id_type.get("id")

        # Datos comunes
        person_name = doc.get("personName")
        person_email = doc.get("personEmail")
        person_id = doc.get("personId")

        # Campos específicos HUMANA (solo presentes si peopleType = Humana)
        domicilio_humana = doc.get("domicilio_0")
        piso_humana = doc.get("piso_1")
        departamento_humana = doc.get("departamento_2")

        # Campos específicos JURÍDICA (solo presentes si peopleType = Jurídica)
        tipo_persona_juridica = doc.get("tipo_de_persona_juridica_0")
        tipo_asociacion = doc.get("tipo_de_asociacion_1")
        tipo_organismo = doc.get("tipo_de_organismo_2")
        tipo_sociedad = doc.get("tipo_de_sociedad_3")
        direccion_juridica = doc.get("direccion_4")

        # Campos dinámicos → JSONB
        dynamic_fields = self._extract_dynamic_fields(doc)

        # Metadata
        people_content = doc.get("peopleContent")
        customer_id = shared_entities.get("customer_id")

        # Auditoría con fallback a NOW() si vienen nulos
        now = datetime.now(timezone.utc)
        created_by_user_id = shared_entities.get("created_by_user_id")
        updated_by_user_id = shared_entities.get("updated_by_user_id")
        created_at = self._parse_timestamp(doc.get("createdAt")) or now
        updated_at = self._parse_timestamp(doc.get("updatedAt")) or created_at

        # Metadata técnica
        deleted = doc.get("deleted", False)
        lumbre_version = doc.get("lumbreVersion")
        __v = doc.get("__v")

        return (
            people_id,
            people_type_id,
            person_id_type_id,
            person_name,
            person_email,
            person_id,
            domicilio_humana,
            piso_humana,
            departamento_humana,
            tipo_persona_juridica,
            tipo_asociacion,
            tipo_organismo,
            tipo_sociedad,
            direccion_juridica,
            dynamic_fields,
            people_content,
            customer_id,
            created_by_user_id,
            updated_by_user_id,
            created_at,
            updated_at,
            deleted,
            lumbre_version,
            __v,
        )

    def _extract_people_type(self, doc):
        """
        Extrae el catálogo de people_type embebido.

        Args:
            doc: Documento MongoDB

        Returns:
            tuple | None: (id, name, alias) o None si no existe
        """
        people_type_id = doc.get("peopleTypeId")
        people_type_name = doc.get("peopleTypeName")
        people_type_alias = doc.get("peopleTypeAlias")

        if people_type_id:
            return (people_type_id, people_type_name, people_type_alias)

        return None

    def _extract_person_id_type(self, doc):
        """
        Extrae el catálogo de person_id_type embebido.

        Args:
            doc: Documento MongoDB

        Returns:
            tuple | None: (id, name) o None si no existe
        """
        person_id_type = doc.get("personIdType", {})

        if isinstance(person_id_type, dict):
            id_type_id = person_id_type.get("id")
            id_type_name = person_id_type.get("name")

            if id_type_id:
                return (id_type_id, id_type_name)

        return None

    def _extract_dynamic_fields(self, doc):
        """
        Extrae campos dinámicos (_3, _4, _5, _6, _7) y los serializa a JSONB.

        Estos campos contienen datos de formulario con estructura variable:
        - Algunos usan group_0.campo_de_texto_0
        - Otros usan group_0._undefined
        - La mayoría son null o string vacío

        Args:
            doc: Documento MongoDB

        Returns:
            str | None: JSON string o None si no hay campos dinámicos
        """
        dynamic_fields = {}

        # Lista de campos dinámicos conocidos
        field_names = ["_3", "_4", "_5", "_6", "_7"]

        for field_name in field_names:
            value = doc.get(field_name)

            # Solo agregar si tiene valor real (no null ni string vacío)
            if value and value != "":
                dynamic_fields[field_name] = value

        # Si hay campos, serializar a JSON
        if dynamic_fields:
            return json.dumps(dynamic_fields, ensure_ascii=False)

        return None

    def _parse_timestamp(self, value):
        """
        Convierte timestamp de MongoDB a formato compatible con PostgreSQL.

        Maneja múltiples formatos:
        - datetime nativo de pymongo (el más común)
        - ISO8601 con 'Z': '2021-03-22T07:49:18.242Z'
        - ISO8601 con timezone: '2022-06-02T13:54:12.273+00:00'
        - Extended JSON: {'$date': '...'}
        - None → retorna None

        Args:
            value: Timestamp en formato MongoDB

        Returns:
            datetime | None: Timestamp parseado o None
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

            # Caso 3: String con formato ISO8601
            if isinstance(value, str):
                # Intentar con 'Z' al final
                if value.endswith("Z"):
                    if "." in value:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
                    else:
                        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")

                # Intentar con timezone explícito (+00:00, +05:30, etc.)
                if "+" in value or value.count("-") > 2:
                    return datetime.fromisoformat(value)

        except (ValueError, TypeError):
            return None

        return None

    # =========================================================================
    # MÉTODOS PRIVADOS: INSERCIÓN
    # =========================================================================

    def _insert_people_types_batch(self, records, cursor):
        """
        Inserta catálogo de tipos de persona con UPSERT.

        Usa DO UPDATE para permitir corrección de nombres si cambian.

        Args:
            records: Lista de tuplas (id, name, alias)
            cursor: Cursor de psycopg2
        """
        # Eliminar duplicados manteniendo el primer valor
        unique = list({r[0]: r for r in records}.values())

        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.people_types (id, name, alias) 
            VALUES %s 
            ON CONFLICT (id) DO UPDATE SET 
                name = EXCLUDED.name,
                alias = EXCLUDED.alias
            """,
            unique,
            template="(%s, %s, %s)",
            page_size=500,
        )

    def _insert_person_id_types_batch(self, records, cursor):
        """
        Inserta catálogo de tipos de documento con UPSERT.

        Usa DO UPDATE para permitir corrección de nombres si cambian.

        Args:
            records: Lista de tuplas (id, name)
            cursor: Cursor de psycopg2
        """
        # Eliminar duplicados manteniendo el primer valor
        unique = list({r[0]: r for r in records}.values())

        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.person_id_types (id, name) 
            VALUES %s 
            ON CONFLICT (id) DO UPDATE SET 
                name = EXCLUDED.name
            """,
            unique,
            template="(%s, %s)",
            page_size=500,
        )

    def _insert_main_batch(self, records, cursor):
        """
        Inserta batch en lml_people.main con UPSERT.

        Usa DO NOTHING para preservar el primer insert completo.

        Args:
            records: Lista de tuplas con datos de personas
            cursor: Cursor de psycopg2
        """
        execute_values(
            cursor,
            f"""
            INSERT INTO {self.schema}.main (
                people_id, people_type_id, person_id_type_id,
                person_name, person_email, person_id,
                domicilio_humana, piso_humana, departamento_humana,
                tipo_persona_juridica, tipo_asociacion, tipo_organismo, tipo_sociedad, direccion_juridica,
                dynamic_fields,
                people_content, customer_id,
                created_by_user_id, updated_by_user_id,
                created_at, updated_at,
                deleted, lumbre_version, __v
            ) VALUES %s
            ON CONFLICT (people_id) DO NOTHING
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=500,
        )
