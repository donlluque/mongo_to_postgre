# analyze_people.py
"""
Script de análisis estructural para lml_people_mesa4core.

Analiza la estructura de documentos de personas, detecta:
- Campos de primer nivel y su cobertura
- Campos dinámicos (_0, _1, _2, etc.) y su contenido
- Catálogos embebidos (peopleType, personIdType)
- Referencias a entidades compartidas (users, customers)
- Arrays y su cardinalidad
- Tipos de datos y valores nulos

Genera reporte completo en samples/lml_people_analysis.txt
"""

import json
import sys
import io
from collections import defaultdict
from pathlib import Path

# Forzar UTF-8 para emojis en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Configuración
SAMPLE_FILE = "samples/lml_people_mesa4core_sample.json"
OUTPUT_FILE = "samples/lml_people_analysis.txt"


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
    Retorna dict con stats por campo.
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

            # Contar nulls
            if value is None or value == "":
                field_stats[field_name]["null_count"] += 1

            # Detectar tipo
            if value is None:
                field_type = "null"
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

            # Guardar samples (primeros 3 valores únicos no-null)
            if len(field_stats[field_name]["sample_values"]) < 3 and value not in [
                None,
                "",
            ]:
                if value not in field_stats[field_name]["sample_values"]:
                    # Para objetos y arrays, convertir a string
                    if isinstance(value, (dict, list)):
                        field_stats[field_name]["sample_values"].append(
                            json.dumps(value, default=str)[:100]
                        )
                    else:
                        field_stats[field_name]["sample_values"].append(
                            str(value)[:100]
                        )

    # Calcular cobertura porcentual
    for field_name, stats in field_stats.items():
        stats["coverage"] = (stats["count"] / total_docs) * 100
        stats["types"] = list(stats["types"])

    return field_stats


def analyze_dynamic_fields(documents):
    """
    Analiza campos dinámicos que siguen patrón _N (ej: _0, _1, _2, _3).
    Retorna dict con stats de cada campo dinámico.
    """
    dynamic_fields = {}  # Cambiar de defaultdict a dict normal

    for doc in documents:
        for field_name, value in doc.items():
            # Detectar campos dinámicos (empiezan con _)
            if field_name.startswith("_") and field_name[1:].isdigit():
                # Inicializar estructura si es la primera vez que vemos este campo
                if field_name not in dynamic_fields:
                    dynamic_fields[field_name] = {
                        "count": 0,
                        "types": set(),
                        "nested_structure": {},
                    }

                dynamic_fields[field_name]["count"] += 1

                # Detectar tipo
                if value is None or value == "":
                    field_type = "null/empty"
                elif isinstance(value, dict):
                    field_type = "object"
                    # Analizar estructura anidada
                    for nested_key in value.keys():
                        if (
                            nested_key
                            not in dynamic_fields[field_name]["nested_structure"]
                        ):
                            dynamic_fields[field_name]["nested_structure"][
                                nested_key
                            ] = 0
                        dynamic_fields[field_name]["nested_structure"][nested_key] += 1
                elif isinstance(value, str):
                    field_type = "string"
                else:
                    field_type = type(value).__name__

                dynamic_fields[field_name]["types"].add(field_type)

    # Convertir sets a listas para serialización JSON
    for field_name, stats in dynamic_fields.items():
        stats["types"] = list(stats["types"])

    return dynamic_fields


def extract_embedded_catalogs(documents):
    """
    Extrae catálogos embebidos (peopleTypeId, personIdType).
    Retorna dict con valores únicos de cada catálogo.
    """
    catalogs = {
        "people_types": {},  # {id: {name, alias, count}}
        "person_id_types": {},  # {id: {name, count}}
    }

    for doc in documents:
        # Analizar peopleType (vía peopleTypeId, peopleTypeName, peopleTypeAlias)
        people_type_id = doc.get("peopleTypeId")
        people_type_name = doc.get("peopleTypeName")
        people_type_alias = doc.get("peopleTypeAlias")

        if people_type_id:
            if people_type_id not in catalogs["people_types"]:
                catalogs["people_types"][people_type_id] = {
                    "name": people_type_name,
                    "alias": people_type_alias,
                    "count": 0,
                }
            catalogs["people_types"][people_type_id]["count"] += 1

        # Analizar personIdType
        person_id_type = doc.get("personIdType")
        if person_id_type and isinstance(person_id_type, dict):
            id_type_id = person_id_type.get("id")
            id_type_name = person_id_type.get("name")

            if id_type_id:
                if id_type_id not in catalogs["person_id_types"]:
                    catalogs["person_id_types"][id_type_id] = {
                        "name": id_type_name,
                        "count": 0,
                    }
                catalogs["person_id_types"][id_type_id]["count"] += 1

    return catalogs


def analyze_user_references(documents):
    """
    Analiza referencias a usuarios en createdBy/updatedBy.
    Retorna stats sobre estructura de snapshots de usuario.
    """
    user_refs = {
        "createdBy": {"present": 0, "missing": 0, "user_ids": set()},
        "updatedBy": {"present": 0, "missing": 0, "user_ids": set()},
    }

    for doc in documents:
        # Analizar createdBy
        created_by = doc.get("createdBy")
        if created_by and isinstance(created_by, dict):
            user = created_by.get("user")
            if user and isinstance(user, dict):
                user_refs["createdBy"]["present"] += 1
                user_id = user.get("id")
                if user_id:
                    user_refs["createdBy"]["user_ids"].add(user_id)
            else:
                user_refs["createdBy"]["missing"] += 1
        else:
            user_refs["createdBy"]["missing"] += 1

        # Analizar updatedBy
        updated_by = doc.get("updatedBy")
        if updated_by and isinstance(updated_by, dict):
            user = updated_by.get("user")
            if user and isinstance(user, dict):
                user_refs["updatedBy"]["present"] += 1
                user_id = user.get("id")
                if user_id:
                    user_refs["updatedBy"]["user_ids"].add(user_id)
            else:
                user_refs["updatedBy"]["missing"] += 1
        else:
            user_refs["updatedBy"]["missing"] += 1

    # Convertir sets a listas para serialización
    user_refs["createdBy"]["user_ids"] = list(user_refs["createdBy"]["user_ids"])
    user_refs["updatedBy"]["user_ids"] = list(user_refs["updatedBy"]["user_ids"])
    user_refs["createdBy"]["unique_users"] = len(user_refs["createdBy"]["user_ids"])
    user_refs["updatedBy"]["unique_users"] = len(user_refs["updatedBy"]["user_ids"])

    return user_refs


def generate_report(documents):
    """
    Genera reporte completo de análisis y lo guarda en archivo.
    """
    total_docs = len(documents)

    # Ejecutar todos los análisis
    field_stats = analyze_field_coverage(documents)
    dynamic_stats = analyze_dynamic_fields(documents)
    catalogs = extract_embedded_catalogs(documents)
    user_refs = analyze_user_references(documents)

    # Preparar contenido del reporte
    lines = []
    lines.append("=" * 80)
    lines.append("ANÁLISIS ESTRUCTURAL: lml_people_mesa4core")
    lines.append("=" * 80)
    lines.append(f"\n📊 Total documentos analizados: {total_docs}\n")

    # 1. CAMPOS DE PRIMER NIVEL
    lines.append("\n" + "=" * 80)
    lines.append("1. CAMPOS DE PRIMER NIVEL")
    lines.append("=" * 80)
    lines.append(f"{'Campo':<30} {'Cobertura':<15} {'Tipos':<20} {'Nulls'}")
    lines.append("-" * 80)

    # Ordenar por nombre de campo
    for field_name in sorted(field_stats.keys()):
        stats = field_stats[field_name]
        coverage = f"{stats['count']}/{total_docs} ({stats['coverage']:.0f}%)"
        types_str = ", ".join(stats["types"])
        null_info = f"{stats['null_count']}" if stats["null_count"] > 0 else "-"
        lines.append(f"{field_name:<30} {coverage:<15} {types_str:<20} {null_info}")

        # Mostrar samples si existen
        if stats["sample_values"]:
            for sample in stats["sample_values"][:2]:
                lines.append(f"  └─ Ejemplo: {sample}")

    # 2. CAMPOS DINÁMICOS
    if dynamic_stats:
        lines.append("\n" + "=" * 80)
        lines.append("2. CAMPOS DINÁMICOS (Patrón _N)")
        lines.append("=" * 80)
        lines.append(
            "Estos campos tienen nombres como _0, _1, _2, etc. y contienen datos de formulario.\n"
        )

        for field_name in sorted(dynamic_stats.keys()):
            stats = dynamic_stats[field_name]
            lines.append(f"\n{field_name}:")
            lines.append(f"  Apariciones: {stats['count']}/{total_docs}")
            lines.append(f"  Tipos: {', '.join(stats['types'])}")

            if stats["nested_structure"]:
                lines.append("  Estructura anidada detectada:")
                for nested_key, count in sorted(stats["nested_structure"].items()):
                    lines.append(f"    • {nested_key}: {count} docs")

    # 3. CATÁLOGOS EMBEBIDOS
    lines.append("\n" + "=" * 80)
    lines.append("3. CATÁLOGOS EMBEBIDOS")
    lines.append("=" * 80)

    lines.append("\n3.1. PEOPLE TYPES (Tipos de Persona)")
    lines.append("-" * 80)
    if catalogs["people_types"]:
        for pt_id, pt_data in catalogs["people_types"].items():
            lines.append(f"  {pt_id}:")
            lines.append(f"    Nombre: {pt_data['name']}")
            lines.append(f"    Alias: {pt_data['alias']}")
            lines.append(f"    Documentos: {pt_data['count']}")
    else:
        lines.append("  (No se encontraron people types)")

    lines.append("\n3.2. PERSON ID TYPES (Tipos de Documento)")
    lines.append("-" * 80)
    if catalogs["person_id_types"]:
        for idt_id, idt_data in catalogs["person_id_types"].items():
            lines.append(f"  {idt_id}:")
            lines.append(f"    Nombre: {idt_data['name']}")
            lines.append(f"    Documentos: {idt_data['count']}")
    else:
        lines.append("  (No se encontraron person ID types)")

    # 4. REFERENCIAS A USUARIOS
    lines.append("\n" + "=" * 80)
    lines.append("4. REFERENCIAS A USUARIOS (Auditoría)")
    lines.append("=" * 80)
    lines.append("\n4.1. createdBy")
    lines.append(f"  Presente: {user_refs['createdBy']['present']}/{total_docs}")
    lines.append(f"  Faltante: {user_refs['createdBy']['missing']}/{total_docs}")
    lines.append(f"  Usuarios únicos: {user_refs['createdBy']['unique_users']}")

    lines.append("\n4.2. updatedBy")
    lines.append(f"  Presente: {user_refs['updatedBy']['present']}/{total_docs}")
    lines.append(f"  Faltante: {user_refs['updatedBy']['missing']}/{total_docs}")
    lines.append(f"  Usuarios únicos: {user_refs['updatedBy']['unique_users']}")

    # 5. DOCUMENTOS COMPLETOS (MUESTRAS)
    lines.append("\n" + "=" * 80)
    lines.append("5. DOCUMENTOS COMPLETOS (Muestras)")
    lines.append("=" * 80)
    lines.append("\nSe muestran 3 documentos: primero, medio y último del sample.\n")

    indices = [0, total_docs // 2, total_docs - 1]
    for i, idx in enumerate(indices, 1):
        lines.append(f"\n{'─' * 80}")
        lines.append(f"Documento {i} (índice {idx}):")
        lines.append("─" * 80)
        lines.append(
            json.dumps(documents[idx], indent=2, default=str, ensure_ascii=False)
        )

    # 6. RECOMENDACIONES DE NORMALIZACIÓN
    lines.append("\n" + "=" * 80)
    lines.append("6. RECOMENDACIONES DE NORMALIZACIÓN")
    lines.append("=" * 80)
    lines.append(
        """
BASADO EN EL ANÁLISIS, SE RECOMIENDA:

1. TABLA PRINCIPAL (lml_people.main):
   - people_id (PK)
   - people_type_id (FK a catálogo people_types)
   - person_name, person_email, person_id
   - person_id_type_id (FK a catálogo person_id_types)
   - customer_id (FK a lml_users o public según arquitectura)
   - created_by_user_id, updated_by_user_id (FK a lml_users.main)
   - created_at, updated_at
   - deleted, lumbre_version

2. CATÁLOGOS PROPIOS:
   - lml_people.people_types (id, name, alias)
   - lml_people.person_id_types (id, name)

3. CAMPOS DINÁMICOS:
   Opción A: JSONB column 'dynamic_fields' (si estructura muy variable)
   Opción B: Tabla normalizada lml_people.dynamic_fields (si estructura predecible)
   
   CRITERIO: Revisar estructura de _0, _1, _2, etc. en documentos completos.
   Si todos siguen patrón group_0.campo_de_texto_0, normalizar.
   Si estructura varía mucho entre documentos, usar JSONB.

4. REFERENCIAS A USUARIOS:
   - Snapshots createdBy/updatedBy → solo almacenar user_id
   - NO duplicar datos de usuario, usar FK a lml_users.main

5. CAMPOS ESPECÍFICOS:
   - domicilio_0, piso_1, departamento_2 → campos individuales o JSONB según variabilidad
   - peopleContent → si es NULL mayormente, hacer nullable
"""
    )

    # Escribir reporte a archivo
    report_content = "\n".join(lines)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"✅ Reporte generado: {OUTPUT_FILE}")
    print(f"📄 Tamaño: {len(report_content) / 1024:.2f} KB")

    return report_content


def main():
    """Función principal."""
    print("🔍 Analizando lml_people_mesa4core...\n")

    # Cargar sample
    documents = load_sample()
    if not documents:
        sys.exit(1)

    print(f"✅ Cargados {len(documents)} documentos")

    # Generar y guardar reporte
    generate_report(documents)

    print("\n✨ Análisis completado")
    print(f"📖 Revisa el archivo {OUTPUT_FILE} para ver el reporte completo")


if __name__ == "__main__":
    main()
