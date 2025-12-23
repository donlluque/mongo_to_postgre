# analyze_processtypes.py
"""
Script de análisis estructural para lml_processtypes_mesa4core.
Genera reporte completo para diseño de schema PostgreSQL.

Output: samples/lml_processtypes_analysis.txt
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime

import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Configuración
SAMPLE_FILE = Path("samples/lml_processtypes_mesa4core_sample.json")
OUTPUT_FILE = Path("samples/lml_processtypes_analysis.txt")


def load_sample():
    """Carga el archivo JSON de sample."""
    try:
        with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] No se encontró: {SAMPLE_FILE}")
        return None
    except json.JSONDecodeError as e:
        print(f"[ERROR] Error al parsear JSON: {e}")
        return None


def analyze_field_coverage(documents):
    """
    Analiza campos de primer nivel: cobertura, tipos, samples.
    """
    field_stats = {}
    total_docs = len(documents)

    for doc in documents:
        for field_name in doc.keys():
            if field_name not in field_stats:
                field_stats[field_name] = {
                    "count": 0,
                    "types": set(),
                    "sample_values": [],
                    "null_count": 0,
                }

            field_stats[field_name]["count"] += 1
            value = doc.get(field_name)

            # Detectar tipo
            if value is None:
                field_type = "null"
                field_stats[field_name]["null_count"] += 1
            elif isinstance(value, dict):
                field_type = "object"
            elif isinstance(value, list):
                field_type = "array"
            elif isinstance(value, bool):
                field_type = "boolean"
            elif isinstance(value, int):
                field_type = "integer"
            elif isinstance(value, float):
                field_type = "float"
            else:
                field_type = "string"

            field_stats[field_name]["types"].add(field_type)

            # Guardar samples (hasta 3 valores únicos representativos)
            if len(field_stats[field_name]["sample_values"]) < 3 and value is not None:
                if isinstance(value, list):
                    sample_repr = f"array[{len(value)}]"
                elif isinstance(value, dict):
                    keys = list(value.keys())[:5]
                    sample_repr = f"object{{{', '.join(keys)}}}"
                else:
                    sample_repr = str(value)[:60]

                if sample_repr not in field_stats[field_name]["sample_values"]:
                    field_stats[field_name]["sample_values"].append(sample_repr)

    # Calcular cobertura
    for field_name, stats in field_stats.items():
        stats["coverage"] = (stats["count"] / total_docs) * 100
        stats["types"] = list(stats["types"])

    return field_stats


def analyze_arrays(documents):
    """
    Analiza arrays: cardinalidad, estructura interna, campos de objetos.
    """
    array_stats = {}

    # Arrays conocidos de processtypes (basado en sample)
    known_arrays = [
        "processFields",
        "processTypeSteps",
    ]

    # Detectar todos los arrays dinámicamente
    for doc in documents:
        for key, value in doc.items():
            if isinstance(value, list):
                if key not in array_stats:
                    array_stats[key] = {
                        "sizes": [],
                        "docs_with_array": 0,
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

                # Analizar contenido
                for item in value:
                    if isinstance(item, dict):
                        stats["content_type"] = "objects"
                        stats["object_keys"].update(item.keys())

                        # Guardar sample
                        if len(stats["sample_items"]) < 2:
                            stats["sample_items"].append(item)
                    else:
                        stats["content_type"] = "primitives"

    return array_stats


def analyze_nested_objects(documents):
    """
    Analiza objetos anidados: estructura, campos internos.
    """
    object_stats = {}

    for doc in documents:
        for key, value in doc.items():
            if isinstance(value, dict) and not key.startswith("_"):
                if key not in object_stats:
                    object_stats[key] = {"count": 0, "keys": Counter(), "sample": None}

                object_stats[key]["count"] += 1
                object_stats[key]["keys"].update(value.keys())

                if object_stats[key]["sample"] is None:
                    object_stats[key]["sample"] = value

    return object_stats


def analyze_user_snapshots(documents):
    """
    Analiza snapshots de usuarios (createdBy/updatedBy).
    """
    snapshots = {
        "createdBy": {"count": 0, "user_ids": set(), "structure": None},
        "updatedBy": {"count": 0, "user_ids": set(), "structure": None},
    }

    for doc in documents:
        for field in ["createdBy", "updatedBy"]:
            value = doc.get(field)
            if isinstance(value, dict):
                snapshots[field]["count"] += 1

                # Extraer user_id
                user = value.get("user", {})
                if isinstance(user, dict):
                    user_id = user.get("id") or user.get("_id")
                    if user_id:
                        if isinstance(user_id, dict):
                            user_id = user_id.get("$oid")
                        snapshots[field]["user_ids"].add(str(user_id))

                # Guardar estructura
                if snapshots[field]["structure"] is None:
                    snapshots[field]["structure"] = value

    return snapshots


def analyze_foreign_keys(documents):
    """
    Detecta posibles foreign keys a otras colecciones.
    """
    fk_candidates = {
        "customerId": {"count": 0, "unique_values": set()},
        "listbuilderId": {"count": 0, "unique_values": set()},
        "formbuilderId": {"count": 0, "unique_values": set()},
        "_master": {"count": 0, "unique_values": set()},
    }

    for doc in documents:
        for field, stats in fk_candidates.items():
            value = doc.get(field)
            if value:
                stats["count"] += 1
                stats["unique_values"].add(str(value))

    return fk_candidates


def analyze_enum_candidates(documents):
    """
    Detecta campos que podrían ser enums (pocos valores únicos).
    """
    string_fields = defaultdict(set)

    # Campos candidatos a enum
    candidates = [
        "typeNumerator",
        "typeComments",
        "typeCanBeTaken",
        "lumbreVersion",
        "deleted",
        "published",
        "isEditable",
        "tadAvailable",
    ]

    for doc in documents:
        for field in candidates:
            value = doc.get(field)
            if value is not None:
                string_fields[field].add(str(value))

    return {k: list(v) for k, v in string_fields.items()}


def generate_report(
    documents,
    field_stats,
    array_stats,
    object_stats,
    snapshots,
    fk_candidates,
    enum_candidates,
    output,
):
    """
    Genera el reporte completo.
    """

    def write(line=""):
        output.append(line)

    total_docs = len(documents)

    # === HEADER ===
    write("=" * 80)
    write("ANÁLISIS ESTRUCTURAL: lml_processtypes_mesa4core")
    write(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    write("=" * 80)
    write()
    write(f"📊 Total documentos analizados: {total_docs}")
    write()

    # === 1. CAMPOS DE PRIMER NIVEL ===
    write("=" * 80)
    write("1. CAMPOS DE PRIMER NIVEL (ordenados por cobertura)")
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
            write(f"  Samples: {', '.join(stats['sample_values'][:3])}")

    # === 2. ARRAYS ===
    write()
    write("=" * 80)
    write("2. ARRAYS (candidatos a tablas relacionadas)")
    write("=" * 80)

    for field_name, stats in sorted(array_stats.items()):
        if not stats["sizes"]:
            continue

        write(f"\n{field_name}:")
        write(f"  Docs con array: {stats['docs_with_array']}/{total_docs}")
        write(
            f"  Cardinalidad: min={min(stats['sizes'])}, max={max(stats['sizes'])}, avg={sum(stats['sizes'])/len(stats['sizes']):.1f}"
        )
        write(f"  Contenido: {stats['content_type']}")

        if stats["object_keys"]:
            top_keys = stats["object_keys"].most_common(10)
            write(f"  Keys en objetos: {', '.join([k for k, _ in top_keys])}")

        if stats["sample_items"]:
            write(f"  Sample item:")
            write(
                f"    {json.dumps(stats['sample_items'][0], indent=4, default=str)[:500]}"
            )

    # === 3. OBJETOS ANIDADOS ===
    write()
    write("=" * 80)
    write("3. OBJETOS ANIDADOS (candidatos a columnas o JSONB)")
    write("=" * 80)

    for field_name, stats in sorted(object_stats.items()):
        write(f"\n{field_name}:")
        write(f"  Presencia: {stats['count']}/{total_docs} docs")
        top_keys = stats["keys"].most_common(10)
        write(f"  Keys: {', '.join([k for k, _ in top_keys])}")
        if stats["sample"]:
            sample_str = json.dumps(stats["sample"], indent=4, default=str)
            if len(sample_str) > 400:
                sample_str = sample_str[:400] + "..."
            write(f"  Sample:")
            for line in sample_str.split("\n"):
                write(f"    {line}")

    # === 4. SNAPSHOTS DE USUARIO ===
    write()
    write("=" * 80)
    write("4. SNAPSHOTS DE USUARIO (createdBy/updatedBy)")
    write("=" * 80)

    for field, stats in snapshots.items():
        write(f"\n{field}:")
        write(f"  Presencia: {stats['count']}/{total_docs} docs")
        write(f"  Usuarios únicos: {len(stats['user_ids'])}")
        if stats["structure"]:
            write(f"  Estructura:")
            struct_str = json.dumps(stats["structure"], indent=4, default=str)
            if len(struct_str) > 600:
                struct_str = struct_str[:600] + "..."
            for line in struct_str.split("\n"):
                write(f"    {line}")

    # === 5. FOREIGN KEYS ===
    write()
    write("=" * 80)
    write("5. FOREIGN KEYS POTENCIALES")
    write("=" * 80)

    for field, stats in fk_candidates.items():
        if stats["count"] > 0:
            write(f"\n{field}:")
            write(
                f"  Presencia: {stats['count']}/{total_docs} docs ({stats['count']*100//total_docs}%)"
            )
            write(f"  Valores únicos: {len(stats['unique_values'])}")

    # === 6. ENUMS CANDIDATOS ===
    write()
    write("=" * 80)
    write("6. CAMPOS ENUM/BOOLEAN (valores únicos)")
    write("=" * 80)

    for field, values in sorted(enum_candidates.items()):
        write(f"\n{field}:")
        write(f"  Valores: {values}")

    # === 7. RECOMENDACIONES ===
    write()
    write("=" * 80)
    write("7. RECOMENDACIONES DE DISEÑO")
    write("=" * 80)

    write("\n7.1 TABLA MAIN (campos escalares):")
    scalar_fields = [
        f
        for f, s in field_stats.items()
        if "array" not in s["types"] and "object" not in s["types"]
    ]
    for f in scalar_fields:
        coverage = field_stats[f]["coverage"]
        nullable = "NULL" if coverage < 100 else "NOT NULL"
        write(f"  - {f} ({nullable}, {coverage:.0f}%)")

    write("\n7.2 TABLAS RELACIONADAS (arrays con objetos):")
    for field_name, stats in array_stats.items():
        if stats["content_type"] == "objects" and stats["sizes"]:
            avg_size = sum(stats["sizes"]) / len(stats["sizes"])
            if avg_size > 0:
                write(f"  - {field_name}: avg {avg_size:.1f} items/doc")

    write("\n7.3 JSONB RECOMENDADO (estructura variable/metadata):")
    jsonb_candidates = []
    for field_name, stats in object_stats.items():
        if len(stats["keys"]) > 3:  # Estructura compleja
            jsonb_candidates.append(field_name)
    for f in jsonb_candidates:
        write(f"  - {f}")

    write("\n7.4 FOREIGN KEYS A DEFINIR:")
    write("  - created_by_user_id → lml_users.main(id)")
    write("  - updated_by_user_id → lml_users.main(id)")
    write("  - customer_id → (verificar si existe tabla customers)")
    if fk_candidates["listbuilderId"]["count"] > 0:
        write("  - listbuilder_id → lml_listbuilder.main(listbuilder_id)")
    if fk_candidates["formbuilderId"]["count"] > 0:
        write("  - formbuilder_id → lml_formbuilder.main(formbuilder_id)")

    return output


def main():
    print(f"[*] Cargando {SAMPLE_FILE}...")
    documents = load_sample()

    if not documents:
        return

    print(f"[OK] {len(documents)} documentos cargados")
    print("[*] Analizando estructura...")

    # Ejecutar análisis
    field_stats = analyze_field_coverage(documents)
    array_stats = analyze_arrays(documents)
    object_stats = analyze_nested_objects(documents)
    snapshots = analyze_user_snapshots(documents)
    fk_candidates = analyze_foreign_keys(documents)
    enum_candidates = analyze_enum_candidates(documents)

    # Generar reporte
    output = []
    generate_report(
        documents,
        field_stats,
        array_stats,
        object_stats,
        snapshots,
        fk_candidates,
        enum_candidates,
        output,
    )

    # Escribir a archivo
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"\n[OK] Reporte generado: {OUTPUT_FILE}")

    # También imprimir a consola
    print("\n" + "=" * 80)
    print("PREVIEW DEL REPORTE (primeras 100 líneas):")
    print("=" * 80)
    for line in output[:100]:
        print(line)
    if len(output) > 100:
        print(f"\n... ({len(output) - 100} líneas más en el archivo)")


if __name__ == "__main__":
    main()
