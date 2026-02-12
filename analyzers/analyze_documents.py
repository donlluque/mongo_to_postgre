# analyze_documents.py
"""
Script de análisis estructural para lml_documents_mesa4core.

Analiza la estructura de documentos digitales, detecta:
- Campos de primer nivel y su cobertura
- Campos dinámicos (generados por formularios: _0, _1, campo_nombre_N)
- Arrays de participantes (signers, reviewers, participants, shareWith)
- Objetos anidados (recipients, viewers, createdBy, updatedBy)
- Catálogos embebidos (lumbreStatus, documentTypePrefix)
- Referencias a entidades compartidas (users, customers)
- Movimientos del documento

Genera reporte completo en samples/lml_documents_analysis.txt
"""

import json
import sys
import io
import re
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime
from pathlib import Path

# Forzar UTF-8 para emojis en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Configuración
# Obtener directorio del script (analyzers/)
SCRIPT_DIR = Path(__file__).resolve().parent

# Subir un nivel (a la raíz del proyecto) y bajar a samples/
SAMPLE_FILE = SCRIPT_DIR.parent / "samples" / "lml_documents_mesa4core_sample.json"
OUTPUT_FILE = SCRIPT_DIR.parent / "samples" / "lml_documents_analysis.txt"


def load_sample():
    """Carga el archivo JSON de sample."""
    try:
        with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"[ERROR] No se encontró el archivo {SAMPLE_FILE}")
        return None
    except json.JSONDecodeError as e:
        print(f"[ERROR] Error al parsear JSON: {e}")
        return None


def analyze_field_coverage(documents):
    """
    Analiza qué campos existen y en cuántos documentos aparecen.
    Separa campos estáticos de campos dinámicos (generados por formularios).
    """
    field_stats = {}
    dynamic_fields = defaultdict(lambda: {"count": 0, "samples": []})
    total_docs = len(documents)

    # Patrón para detectar campos dinámicos (terminan en _N o tienen patrón campo_nombre_N)
    dynamic_pattern = re.compile(r"^(.+)_(\d+)$")

    for doc in documents:
        for field_name in doc.keys():
            # Detectar si es campo dinámico
            match = dynamic_pattern.match(field_name)
            if match and field_name not in [
                "__v",
                "_id",
            ]:  # Excluir campos conocidos de Mongo
                base_name = match.group(1)
                dynamic_fields[field_name]["count"] += 1
                if len(dynamic_fields[field_name]["samples"]) < 2 and doc.get(
                    field_name
                ):
                    dynamic_fields[field_name]["samples"].append(doc.get(field_name))
                continue

            if field_name not in field_stats:
                field_stats[field_name] = {
                    "count": 0,
                    "types": set(),
                    "sample_values": [],
                    "null_count": 0,
                }

            value = doc.get(field_name)
            field_stats[field_name]["count"] += 1

            # Detectar tipo
            if value is None:
                field_stats[field_name]["null_count"] += 1
                field_stats[field_name]["types"].add("null")
            elif isinstance(value, dict):
                field_stats[field_name]["types"].add("object")
            elif isinstance(value, list):
                field_stats[field_name]["types"].add("array")
            elif isinstance(value, bool):
                field_stats[field_name]["types"].add("boolean")
            elif isinstance(value, int):
                field_stats[field_name]["types"].add("integer")
            elif isinstance(value, float):
                field_stats[field_name]["types"].add("float")
            else:
                field_stats[field_name]["types"].add("string")

            # Guardar samples
            if len(field_stats[field_name]["sample_values"]) < 3:
                if value and value not in field_stats[field_name]["sample_values"]:
                    sample_str = str(value)[:100] if value else None
                    if sample_str:
                        field_stats[field_name]["sample_values"].append(sample_str)

    # Calcular cobertura
    for field_name, stats in field_stats.items():
        stats["coverage"] = (stats["count"] / total_docs) * 100
        stats["types"] = list(stats["types"])

    return field_stats, dict(dynamic_fields)


def analyze_arrays(documents):
    """
    Analiza arrays conocidos: participants, signers, reviewers, shareWith, movements, etc.
    """
    array_stats = {}
    known_arrays = [
        "participants",
        "signers",
        "reviewers",
        "shareWith",
        "movements",
    ]

    # Detectar todos los arrays dinámicamente también
    for doc in documents:
        for key, value in doc.items():
            if isinstance(value, list) and key not in array_stats:
                array_stats[key] = {
                    "sizes": [],
                    "docs_with_array": 0,
                    "docs_with_data": 0,
                    "content_type": None,
                    "object_keys": Counter(),
                    "sample_items": [],
                }

    # Analizar cada array
    for doc in documents:
        for field_name, stats in array_stats.items():
            value = doc.get(field_name)

            if isinstance(value, list):
                stats["docs_with_array"] += 1
                stats["sizes"].append(len(value))

                if len(value) > 0:
                    stats["docs_with_data"] += 1

                # Analizar contenido
                for item in value:
                    if isinstance(item, dict):
                        stats["content_type"] = "objects"
                        stats["object_keys"].update(item.keys())

                        if len(stats["sample_items"]) < 2:
                            stats["sample_items"].append(item)
                    elif isinstance(item, str):
                        stats["content_type"] = "strings"
                    else:
                        stats["content_type"] = "primitives"

    return array_stats


def analyze_nested_objects(documents):
    """
    Analiza objetos anidados: recipients, viewers, createdBy, updatedBy, etc.
    """
    object_stats = {}

    # Objetos conocidos de interés
    known_objects = [
        "createdBy",
        "updatedBy",
        "recipients",
        "viewers",
        "documentSteps",
        "lumbreStatus",
        "documentTypePrefix",
        "instancePrivileges",
        "calculatedProps",
        "signerPositionMap",
        "lumbreNextSigner",
        "lumbreNextParticipant",
        "lumbreNextReviewer",
    ]

    for doc in documents:
        for key in known_objects:
            value = doc.get(key)
            if isinstance(value, dict):
                if key not in object_stats:
                    object_stats[key] = {"count": 0, "keys": Counter(), "sample": None}

                object_stats[key]["count"] += 1
                object_stats[key]["keys"].update(value.keys())

                if object_stats[key]["sample"] is None:
                    object_stats[key]["sample"] = value

    return object_stats


def analyze_embedded_catalogs(documents):
    """
    Analiza catálogos embebidos: lumbreStatus, documentTypePrefix, etc.
    """
    catalogs = {
        "lumbreStatus": {},
        "documentTypePrefix": {},
        "documentTypeName": Counter(),
        "documentTypeSignature": Counter(),
        "documentTypeVisibility": Counter(),
        "documentTypeComunicable": Counter(),
    }

    for doc in documents:
        # lumbreStatus (objeto con id y name)
        status = doc.get("lumbreStatus")
        if isinstance(status, dict) and "id" in status:
            status_id = status.get("id")
            if status_id not in catalogs["lumbreStatus"]:
                catalogs["lumbreStatus"][status_id] = {
                    "name": status.get("name"),
                    "count": 0,
                }
            catalogs["lumbreStatus"][status_id]["count"] += 1

        # documentTypePrefix (objeto con id y name)
        prefix = doc.get("documentTypePrefix")
        if isinstance(prefix, dict) and "id" in prefix:
            prefix_id = prefix.get("id")
            if prefix_id not in catalogs["documentTypePrefix"]:
                catalogs["documentTypePrefix"][prefix_id] = {
                    "name": prefix.get("name"),
                    "count": 0,
                }
            catalogs["documentTypePrefix"][prefix_id]["count"] += 1

        # Campos string que actúan como catálogos
        for field in [
            "documentTypeName",
            "documentTypeSignature",
            "documentTypeVisibility",
            "documentTypeComunicable",
        ]:
            value = doc.get(field)
            if value:
                catalogs[field][value] += 1

    return catalogs


def analyze_user_snapshots(documents):
    """
    Analiza snapshots de usuarios en createdBy/updatedBy.
    """
    snapshot_stats = {
        "createdBy": {
            "present": 0,
            "has_user": 0,
            "user_keys": Counter(),
            "unique_user_ids": set(),
        },
        "updatedBy": {
            "present": 0,
            "has_user": 0,
            "user_keys": Counter(),
            "unique_user_ids": set(),
        },
    }

    for doc in documents:
        for field in ["createdBy", "updatedBy"]:
            value = doc.get(field)
            if value:
                snapshot_stats[field]["present"] += 1
                user = value.get("user")
                if user:
                    snapshot_stats[field]["has_user"] += 1
                    snapshot_stats[field]["user_keys"].update(user.keys())
                    user_id = user.get("id") or user.get("_id")
                    if user_id:
                        snapshot_stats[field]["unique_user_ids"].add(str(user_id))

    return snapshot_stats


def analyze_recipients_viewers(documents):
    """
    Analiza estructura de recipients y viewers.
    """
    stats = {
        "recipients": {
            "users": {"docs_with_data": 0, "total_items": 0},
            "areas": {"docs_with_data": 0, "total_items": 0},
            "subareas": {"docs_with_data": 0, "total_items": 0},
            "groups": {"docs_with_data": 0, "total_items": 0},
            "emails": {"docs_with_data": 0, "total_items": 0},
        },
        "viewers": {
            "users": {"docs_with_data": 0, "total_items": 0},
            "areas": {"docs_with_data": 0, "total_items": 0},
            "subareas": {"docs_with_data": 0, "total_items": 0},
        },
    }

    for doc in documents:
        for container in ["recipients", "viewers"]:
            value = doc.get(container)
            if isinstance(value, dict):
                for subkey in stats[container].keys():
                    subvalue = value.get(subkey, [])
                    if isinstance(subvalue, list) and len(subvalue) > 0:
                        stats[container][subkey]["docs_with_data"] += 1
                        stats[container][subkey]["total_items"] += len(subvalue)

    return stats


def generate_report(documents):
    """
    Genera reporte completo de análisis.
    """
    output = []

    def write(line=""):
        output.append(line)

    total_docs = len(documents)

    # === HEADER ===
    write("=" * 80)
    write("ANÁLISIS ESTRUCTURAL: lml_documents_mesa4core")
    write(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    write("=" * 80)
    write()
    write(f"📊 Total documentos analizados: {total_docs}")
    write()

    # === 1. CAMPOS DE PRIMER NIVEL ===
    field_stats, dynamic_fields = analyze_field_coverage(documents)

    write("=" * 80)
    write("1. CAMPOS ESTÁTICOS (ordenados por cobertura)")
    write("=" * 80)

    sorted_fields = sorted(
        field_stats.items(), key=lambda x: x[1]["coverage"], reverse=True
    )

    for field_name, stats in sorted_fields:
        coverage = stats["coverage"]
        types_str = ", ".join(stats["types"])
        write(f"\n{field_name}:")
        write(f"  Cobertura: {coverage:.1f}% ({stats['count']}/{total_docs} docs)")
        write(f"  Tipos: {types_str}")
        if stats["null_count"] > 0:
            write(f"  Nulls: {stats['null_count']}")
        if stats["sample_values"]:
            samples = [str(s)[:80] for s in stats["sample_values"][:2]]
            write(f"  Samples: {samples}")

    # === 2. CAMPOS DINÁMICOS ===
    write()
    write("=" * 80)
    write("2. CAMPOS DINÁMICOS (generados por formularios)")
    write("=" * 80)
    write()
    write(
        "Estos campos tienen nombres variables (terminan en _N) y deberían ir a JSONB."
    )
    write(f"Total campos dinámicos únicos detectados: {len(dynamic_fields)}")
    write()

    # Agrupar por patrón base
    dynamic_pattern = re.compile(r"^(.+)_(\d+)$")
    base_patterns = Counter()
    for field_name in dynamic_fields.keys():
        match = dynamic_pattern.match(field_name)
        if match:
            base_patterns[match.group(1)] += 1

    write("Patrones base más comunes:")
    for pattern, count in base_patterns.most_common(20):
        write(f"  {pattern}_N: {count} variantes")

    # Mostrar algunos ejemplos
    write()
    write("Ejemplos de campos dinámicos:")
    for field_name, stats in list(dynamic_fields.items())[:10]:
        write(f"  {field_name}: {stats['count']} docs")

    # === 3. ARRAYS ===
    array_stats = analyze_arrays(documents)

    write()
    write("=" * 80)
    write("3. ARRAYS (candidatos a tablas relacionadas)")
    write("=" * 80)

    for field_name, stats in sorted(array_stats.items()):
        if not stats["sizes"]:
            continue

        avg_size = sum(stats["sizes"]) / len(stats["sizes"]) if stats["sizes"] else 0
        max_size = max(stats["sizes"]) if stats["sizes"] else 0

        write(f"\n{field_name}:")
        write(f"  Docs con array: {stats['docs_with_array']}/{total_docs}")
        write(f"  Docs con datos: {stats['docs_with_data']}/{total_docs}")
        write(f"  Cardinalidad: min=0, max={max_size}, avg={avg_size:.1f}")
        write(f"  Contenido: {stats['content_type']}")

        if stats["object_keys"]:
            top_keys = stats["object_keys"].most_common(10)
            write(f"  Keys en objetos: {', '.join([k for k, _ in top_keys])}")

        if stats["sample_items"]:
            write(f"  Sample item:")
            sample_str = json.dumps(stats["sample_items"][0], indent=4, default=str)
            if len(sample_str) > 400:
                sample_str = sample_str[:400] + "..."
            for line in sample_str.split("\n"):
                write(f"    {line}")

    # === 4. OBJETOS ANIDADOS ===
    object_stats = analyze_nested_objects(documents)

    write()
    write("=" * 80)
    write("4. OBJETOS ANIDADOS")
    write("=" * 80)

    for field_name, stats in sorted(object_stats.items()):
        write(f"\n{field_name}:")
        write(f"  Presencia: {stats['count']}/{total_docs} docs")
        top_keys = stats["keys"].most_common(15)
        write(f"  Keys: {', '.join([k for k, _ in top_keys])}")
        if stats["sample"]:
            sample_str = json.dumps(stats["sample"], indent=4, default=str)
            if len(sample_str) > 500:
                sample_str = sample_str[:500] + "..."
            write(f"  Sample:")
            for line in sample_str.split("\n"):
                write(f"    {line}")

    # === 5. CATÁLOGOS EMBEBIDOS ===
    catalogs = analyze_embedded_catalogs(documents)

    write()
    write("=" * 80)
    write("5. CATÁLOGOS EMBEBIDOS")
    write("=" * 80)

    write("\n5.1. LUMBRE STATUS (Estados del documento)")
    write("-" * 40)
    for status_id, data in sorted(
        catalogs["lumbreStatus"].items(), key=lambda x: x[1]["count"], reverse=True
    ):
        write(f"  {status_id}: {data['name']} ({data['count']} docs)")

    write("\n5.2. DOCUMENT TYPE PREFIX (Prefijos)")
    write("-" * 40)
    for prefix_id, data in sorted(
        catalogs["documentTypePrefix"].items(),
        key=lambda x: x[1]["count"],
        reverse=True,
    ):
        write(f"  {prefix_id}: {data['name']} ({data['count']} docs)")

    write("\n5.3. DOCUMENT TYPE NAME (Tipos de documento)")
    write("-" * 40)
    for name, count in catalogs["documentTypeName"].most_common():
        write(f"  {name}: {count} docs")

    write("\n5.4. DOCUMENT TYPE SIGNATURE")
    write("-" * 40)
    for name, count in catalogs["documentTypeSignature"].most_common():
        write(f"  {name}: {count} docs")

    write("\n5.5. DOCUMENT TYPE VISIBILITY")
    write("-" * 40)
    for name, count in catalogs["documentTypeVisibility"].most_common():
        write(f"  {name}: {count} docs")

    write("\n5.6. DOCUMENT TYPE COMUNICABLE")
    write("-" * 40)
    for name, count in catalogs["documentTypeComunicable"].most_common():
        write(f"  {name}: {count} docs")

    # === 6. REFERENCIAS A USUARIOS ===
    snapshot_stats = analyze_user_snapshots(documents)

    write()
    write("=" * 80)
    write("6. REFERENCIAS A USUARIOS (Auditoría)")
    write("=" * 80)

    for field, stats in snapshot_stats.items():
        write(f"\n{field}:")
        write(f"  Presente: {stats['present']}/{total_docs}")
        write(f"  Con user object: {stats['has_user']}/{total_docs}")
        write(f"  Usuarios únicos: {len(stats['unique_user_ids'])}")
        if stats["user_keys"]:
            top_keys = stats["user_keys"].most_common(15)
            write(f"  Keys en user: {', '.join([k for k, _ in top_keys])}")

    # === 7. RECIPIENTS Y VIEWERS ===
    rv_stats = analyze_recipients_viewers(documents)

    write()
    write("=" * 80)
    write("7. RECIPIENTS Y VIEWERS (Destinatarios)")
    write("=" * 80)

    for container, subfields in rv_stats.items():
        write(f"\n{container}:")
        for subkey, data in subfields.items():
            if data["docs_with_data"] > 0:
                write(
                    f"  {subkey}: {data['docs_with_data']} docs, {data['total_items']} items totales"
                )
            else:
                write(f"  {subkey}: sin datos")

    # === 8. DOCUMENTOS COMPLETOS (SAMPLES) ===
    write()
    write("=" * 80)
    write("8. DOCUMENTOS COMPLETOS (Muestras)")
    write("=" * 80)
    write()
    write("Se muestran 3 documentos: primero, medio y último del sample.")

    sample_indices = [0, len(documents) // 2, len(documents) - 1]
    for idx in sample_indices:
        doc = documents[idx]
        write(f"\n--- Documento {idx + 1} ---")
        doc_str = json.dumps(doc, indent=2, default=str, ensure_ascii=False)
        if len(doc_str) > 3000:
            doc_str = doc_str[:3000] + "\n... [TRUNCADO]"
        write(doc_str)

    return "\n".join(output)


def main():
    """Función principal."""
    print("🔍 Cargando sample...")
    documents = load_sample()

    if not documents:
        print("❌ No se pudo cargar el sample")
        return

    print(f"✅ Cargados {len(documents)} documentos")
    print("📊 Analizando estructura...")

    report = generate_report(documents)

    # Guardar reporte
    output_path = Path(OUTPUT_FILE)
    output_path.parent.mkdir(exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"✅ Reporte guardado en: {OUTPUT_FILE}")
    print()
    print("=" * 60)
    print("RESUMEN RÁPIDO")
    print("=" * 60)

    # Mostrar resumen en consola
    field_stats, dynamic_fields = analyze_field_coverage(documents)
    array_stats = analyze_arrays(documents)

    print(f"\n📋 Campos estáticos: {len(field_stats)}")
    print(f"📋 Campos dinámicos: {len(dynamic_fields)}")
    print(f"📋 Arrays detectados: {len(array_stats)}")

    # Arrays con datos
    arrays_with_data = [
        name for name, stats in array_stats.items() if stats["docs_with_data"] > 0
    ]
    print(f"📋 Arrays con datos: {len(arrays_with_data)}")
    for name in arrays_with_data[:10]:
        stats = array_stats[name]
        print(f"    - {name}: {stats['docs_with_data']} docs")


if __name__ == "__main__":
    main()
