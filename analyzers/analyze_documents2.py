#!/usr/bin/env python3
"""
Analyzer específico para campos JSONB de lml_documents.

Busca documentos donde los campos que queremos desanidar
tengan datos reales (no vacíos) para entender su estructura.

Campos a analizar:
- recipients (users, areas, subareas, groups, emails)
- viewers (users, areas, subareas)
- document_steps
- instance_privileges
- calculated_props
- lumbre_next_signer
- lumbre_next_participant
- lumbre_next_reviewer
- lumbre_signer_reviewer
- lumbre_substitute
"""

import json
from pathlib import Path
from datetime import datetime

# Rutas relativas al script
SCRIPT_DIR = Path(__file__).resolve().parent
SAMPLE_FILE = SCRIPT_DIR.parent / "samples" / "lml_documents_mesa4core_sample.json"
OUTPUT_FILE = SCRIPT_DIR.parent / "samples" / "lml_documents_jsonb_analysis.txt"


def load_sample():
    """Carga el archivo JSON de muestra."""
    with open(SAMPLE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def has_data(value):
    """Verifica si un valor tiene datos reales."""
    if value is None:
        return False
    if isinstance(value, dict):
        # Para dicts, verificar si algún valor interno tiene datos
        for v in value.values():
            if has_data(v):
                return True
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, str):
        return value.strip() != ""
    return True


def find_docs_with_data(documents, field_name):
    """Encuentra documentos donde un campo tiene datos."""
    docs_with_data = []

    for doc in documents:
        value = doc.get(field_name)
        if has_data(value):
            docs_with_data.append(
                {
                    "_id": doc.get("_id"),
                    "documentName": doc.get("documentName"),
                    field_name: value,
                }
            )

    return docs_with_data


def find_recipients_with_data(documents):
    """Encuentra documentos con recipients que tengan datos en algún subarray."""
    results = {"users": [], "areas": [], "subareas": [], "groups": [], "emails": []}

    for doc in documents:
        recipients = doc.get("recipients", {})
        if not isinstance(recipients, dict):
            continue

        for key in results.keys():
            arr = recipients.get(key, [])
            if arr and len(arr) > 0:
                results[key].append(
                    {
                        "_id": doc.get("_id"),
                        "documentName": doc.get("documentName"),
                        key: arr,
                    }
                )

    return results


def find_viewers_with_data(documents):
    """Encuentra documentos con viewers que tengan datos."""
    results = {"users": [], "areas": [], "subareas": []}

    for doc in documents:
        viewers = doc.get("viewers", {})
        if not isinstance(viewers, dict):
            continue

        for key in results.keys():
            arr = viewers.get(key, [])
            if arr and len(arr) > 0:
                results[key].append(
                    {
                        "_id": doc.get("_id"),
                        "documentName": doc.get("documentName"),
                        key: arr,
                    }
                )

    return results


def analyze_calculated_props(documents):
    """Analiza la estructura de calculated_props."""
    samples = []
    everyone_can_access_values = {"True": 0, "False": 0}
    who_can_access_with_data = []

    for doc in documents:
        calc = doc.get("calculatedProps", {})
        if not isinstance(calc, dict):
            continue

        # Contar everyoneCanAccess
        eca = calc.get("everyoneCanAccess")
        if eca is True:
            everyone_can_access_values["True"] += 1
        elif eca is False:
            everyone_can_access_values["False"] += 1

        # Buscar whoCanAccess con datos
        wca = calc.get("whoCanAccess", {})
        if isinstance(wca, dict):
            has_any = False
            for key, arr in wca.items():
                if isinstance(arr, list) and len(arr) > 0:
                    has_any = True
                    break

            if has_any:
                who_can_access_with_data.append(
                    {
                        "_id": doc.get("_id"),
                        "documentName": doc.get("documentName"),
                        "calculatedProps": calc,
                    }
                )

    return {
        "everyoneCanAccess_distribution": everyone_can_access_values,
        "whoCanAccess_with_data": who_can_access_with_data,
    }


def analyze_document_steps(documents):
    """Analiza document_steps buscando items con datos."""
    with_items = []
    position_values = {}

    for doc in documents:
        steps = doc.get("documentSteps", {})
        if not isinstance(steps, dict):
            continue

        # Contar positions
        pos = steps.get("position")
        if pos is not None:
            pos_str = str(pos)
            position_values[pos_str] = position_values.get(pos_str, 0) + 1

        # Buscar items con datos
        items = steps.get("items", [])
        if items and len(items) > 0:
            with_items.append(
                {
                    "_id": doc.get("_id"),
                    "documentName": doc.get("documentName"),
                    "documentSteps": steps,
                }
            )

    return {"position_distribution": position_values, "with_items": with_items}


def analyze_instance_privileges(documents):
    """Analiza instance_privileges buscando arrays con datos."""
    with_data = []

    for doc in documents:
        priv = doc.get("instancePrivileges", {})
        if not isinstance(priv, dict):
            continue

        has_any = False
        for key, arr in priv.items():
            if isinstance(arr, list) and len(arr) > 0:
                has_any = True
                break

        if has_any:
            with_data.append(
                {
                    "_id": doc.get("_id"),
                    "documentName": doc.get("documentName"),
                    "instancePrivileges": priv,
                }
            )

    return with_data


def generate_report(documents):
    """Genera reporte completo."""

    output = []
    output.append("=" * 80)
    output.append("ANÁLISIS DE CAMPOS JSONB: lml_documents_mesa4core")
    output.append(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append(f"Total documentos: {len(documents)}")
    output.append("=" * 80)

    # =========================================================================
    # 1. RECIPIENTS
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("1. RECIPIENTS (documentos con datos)")
    output.append("=" * 80)

    recipients_data = find_recipients_with_data(documents)

    for key, docs in recipients_data.items():
        output.append(f"\n--- recipients.{key}: {len(docs)} documentos con datos ---")

        if docs:
            # Mostrar hasta 3 ejemplos
            for i, doc in enumerate(docs[:3]):
                output.append(f"\n  Ejemplo {i+1}:")
                output.append(f"    documentName: {doc['documentName']}")
                output.append(
                    f"    {key}: {json.dumps(doc[key], indent=6, ensure_ascii=False)}"
                )

    # =========================================================================
    # 2. VIEWERS
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("2. VIEWERS (documentos con datos)")
    output.append("=" * 80)

    viewers_data = find_viewers_with_data(documents)

    for key, docs in viewers_data.items():
        output.append(f"\n--- viewers.{key}: {len(docs)} documentos con datos ---")

        if docs:
            for i, doc in enumerate(docs[:3]):
                output.append(f"\n  Ejemplo {i+1}:")
                output.append(f"    documentName: {doc['documentName']}")
                output.append(
                    f"    {key}: {json.dumps(doc[key], indent=6, ensure_ascii=False)}"
                )

    # =========================================================================
    # 3. CALCULATED PROPS
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("3. CALCULATED PROPS")
    output.append("=" * 80)

    calc_analysis = analyze_calculated_props(documents)

    output.append(f"\n--- everyoneCanAccess distribution ---")
    output.append(
        f"    True: {calc_analysis['everyoneCanAccess_distribution']['True']}"
    )
    output.append(
        f"    False: {calc_analysis['everyoneCanAccess_distribution']['False']}"
    )

    output.append(
        f"\n--- whoCanAccess con datos: {len(calc_analysis['whoCanAccess_with_data'])} documentos ---"
    )

    for i, doc in enumerate(calc_analysis["whoCanAccess_with_data"][:3]):
        output.append(f"\n  Ejemplo {i+1}:")
        output.append(f"    documentName: {doc['documentName']}")
        output.append(
            f"    calculatedProps: {json.dumps(doc['calculatedProps'], indent=6, ensure_ascii=False)}"
        )

    # =========================================================================
    # 4. DOCUMENT STEPS
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("4. DOCUMENT STEPS")
    output.append("=" * 80)

    steps_analysis = analyze_document_steps(documents)

    output.append(f"\n--- position distribution ---")
    for pos, count in sorted(steps_analysis["position_distribution"].items()):
        output.append(f"    position={pos}: {count} docs")

    output.append(
        f"\n--- documentos con items[]: {len(steps_analysis['with_items'])} ---"
    )

    for i, doc in enumerate(steps_analysis["with_items"][:3]):
        output.append(f"\n  Ejemplo {i+1}:")
        output.append(f"    documentName: {doc['documentName']}")
        output.append(
            f"    documentSteps: {json.dumps(doc['documentSteps'], indent=6, ensure_ascii=False)}"
        )

    # =========================================================================
    # 5. INSTANCE PRIVILEGES
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("5. INSTANCE PRIVILEGES")
    output.append("=" * 80)

    priv_with_data = analyze_instance_privileges(documents)

    output.append(f"\n--- documentos con datos: {len(priv_with_data)} ---")

    for i, doc in enumerate(priv_with_data[:3]):
        output.append(f"\n  Ejemplo {i+1}:")
        output.append(f"    documentName: {doc['documentName']}")
        output.append(
            f"    instancePrivileges: {json.dumps(doc['instancePrivileges'], indent=6, ensure_ascii=False)}"
        )

    # =========================================================================
    # 6. LUMBRE NEXT SIGNER
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("6. LUMBRE NEXT SIGNER")
    output.append("=" * 80)

    next_signer_docs = find_docs_with_data(documents, "lumbreNextSigner")
    output.append(f"\n--- documentos con datos: {len(next_signer_docs)} ---")

    for i, doc in enumerate(next_signer_docs[:3]):
        output.append(f"\n  Ejemplo {i+1}:")
        output.append(f"    documentName: {doc['documentName']}")
        output.append(
            f"    lumbreNextSigner: {json.dumps(doc['lumbreNextSigner'], indent=6, ensure_ascii=False)}"
        )

    # =========================================================================
    # 7. LUMBRE NEXT PARTICIPANT
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("7. LUMBRE NEXT PARTICIPANT")
    output.append("=" * 80)

    next_part_docs = find_docs_with_data(documents, "lumbreNextParticipant")
    output.append(f"\n--- documentos con datos: {len(next_part_docs)} ---")

    for i, doc in enumerate(next_part_docs[:3]):
        output.append(f"\n  Ejemplo {i+1}:")
        output.append(f"    documentName: {doc['documentName']}")
        output.append(
            f"    lumbreNextParticipant: {json.dumps(doc['lumbreNextParticipant'], indent=6, ensure_ascii=False)}"
        )

    # =========================================================================
    # 8. LUMBRE NEXT REVIEWER
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("8. LUMBRE NEXT REVIEWER")
    output.append("=" * 80)

    next_rev_docs = find_docs_with_data(documents, "lumbreNextReviewer")
    output.append(f"\n--- documentos con datos: {len(next_rev_docs)} ---")

    for i, doc in enumerate(next_rev_docs[:3]):
        output.append(f"\n  Ejemplo {i+1}:")
        output.append(f"    documentName: {doc['documentName']}")
        output.append(
            f"    lumbreNextReviewer: {json.dumps(doc['lumbreNextReviewer'], indent=6, ensure_ascii=False)}"
        )

    # =========================================================================
    # 9. LUMBRE SIGNER REVIEWER
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("9. LUMBRE SIGNER REVIEWER")
    output.append("=" * 80)

    signer_rev_docs = find_docs_with_data(documents, "lumbreSignerReviewer")
    output.append(f"\n--- documentos con datos: {len(signer_rev_docs)} ---")

    for i, doc in enumerate(signer_rev_docs[:3]):
        output.append(f"\n  Ejemplo {i+1}:")
        output.append(f"    documentName: {doc['documentName']}")
        output.append(
            f"    lumbreSignerReviewer: {json.dumps(doc['lumbreSignerReviewer'], indent=6, ensure_ascii=False)}"
        )

    # =========================================================================
    # 10. LUMBRE SUBSTITUTE
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("10. LUMBRE SUBSTITUTE")
    output.append("=" * 80)

    substitute_docs = find_docs_with_data(documents, "lumbreSubstitute")
    output.append(f"\n--- documentos con datos: {len(substitute_docs)} ---")

    for i, doc in enumerate(substitute_docs[:3]):
        output.append(f"\n  Ejemplo {i+1}:")
        output.append(f"    documentName: {doc['documentName']}")
        output.append(
            f"    lumbreSubstitute: {json.dumps(doc['lumbreSubstitute'], indent=6, ensure_ascii=False)}"
        )

    # =========================================================================
    # RESUMEN
    # =========================================================================
    output.append("\n" + "=" * 80)
    output.append("RESUMEN")
    output.append("=" * 80)

    output.append("\nCampos con datos encontrados:")
    output.append(f"  recipients.users: {len(recipients_data['users'])} docs")
    output.append(f"  recipients.areas: {len(recipients_data['areas'])} docs")
    output.append(f"  recipients.subareas: {len(recipients_data['subareas'])} docs")
    output.append(f"  recipients.groups: {len(recipients_data['groups'])} docs")
    output.append(f"  recipients.emails: {len(recipients_data['emails'])} docs")
    output.append(f"  viewers.users: {len(viewers_data['users'])} docs")
    output.append(f"  viewers.areas: {len(viewers_data['areas'])} docs")
    output.append(f"  viewers.subareas: {len(viewers_data['subareas'])} docs")
    output.append(
        f"  calculatedProps.whoCanAccess: {len(calc_analysis['whoCanAccess_with_data'])} docs"
    )
    output.append(f"  documentSteps.items: {len(steps_analysis['with_items'])} docs")
    output.append(f"  instancePrivileges: {len(priv_with_data)} docs")
    output.append(f"  lumbreNextSigner: {len(next_signer_docs)} docs")
    output.append(f"  lumbreNextParticipant: {len(next_part_docs)} docs")
    output.append(f"  lumbreNextReviewer: {len(next_rev_docs)} docs")
    output.append(f"  lumbreSignerReviewer: {len(signer_rev_docs)} docs")
    output.append(f"  lumbreSubstitute: {len(substitute_docs)} docs")

    return "\n".join(output)


def main():
    print(f"Cargando {SAMPLE_FILE}...")
    documents = load_sample()
    print(f"Documentos cargados: {len(documents)}")

    print("Analizando campos JSONB...")
    report = generate_report(documents)

    print(f"Guardando reporte en {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print("=" * 60)
    print("✅ Análisis completado")
    print(f"   Reporte guardado en: {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
