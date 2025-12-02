"""
Script de análisis profundo para lml_formbuilder_mesa4core.
Analiza estructura JSON y genera reporte técnico para diseño de schema.
"""

import json
import sys
from collections import Counter
from pathlib import Path
from datetime import datetime

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def analyze_formbuilder():
    """Analiza la estructura completa de lml_formbuilder y genera reporte."""
    
    filepath = Path("samples/lml_formbuilder_mesa4core_sample.json")
    output_file = Path("samples/lml_formbuilder_analysis.txt")
    
    # Cargar JSON
    with open(filepath, 'r', encoding='utf-8') as f:
        docs = json.load(f)
    
    # Preparar output
    output = []
    
    def write(line=""):
        output.append(line)
        print(line)
    
    # === HEADER ===
    write("=" * 70)
    write(f"ANÁLISIS ESTRUCTURAL: lml_formbuilder_mesa4core")
    write(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    write("=" * 70)
    write()
    write(f"📊 Total documentos: {len(docs)}")
    write()
    
    # === 1. CAMPOS DE PRIMER NIVEL ===
    all_keys = Counter()
    for doc in docs:
        all_keys.update(doc.keys())
    
    write("CAMPOS DE PRIMER NIVEL:")
    write("-" * 70)
    for key, count in sorted(all_keys.items()):
        pct = count * 100 // len(docs)
        write(f"  {key:35s} {count:3d}/{len(docs):3d} ({pct:3d}%)")
    write()
    
    # === 2. ANÁLISIS DE ARRAYS ===
    write("=" * 70)
    write("ARRAYS (cardinalidad y estructura):")
    write("-" * 70)
    
    # Detectar todos los campos que son arrays
    array_fields_detected = set()
    for doc in docs:
        for key, value in doc.items():
            if isinstance(value, list) and len(value) > 0:
                array_fields_detected.add(key)
    
    for field in sorted(array_fields_detected):
        sizes = []
        has_objects = False
        has_simple = False
        
        for doc in docs:
            if field in doc and isinstance(doc[field], list):
                sizes.append(len(doc[field]))
                
                # Detectar tipo de contenido
                if len(doc[field]) > 0:
                    if isinstance(doc[field][0], dict):
                        has_objects = True
                    else:
                        has_simple = True
        
        if sizes:
            avg = sum(sizes) / len(sizes)
            content_type = "objects" if has_objects else "simple"
            write(f"  {field:35s} Avg: {avg:5.1f}  Min: {min(sizes):3d}  Max: {max(sizes):3d}  [{content_type}]")
    write()
    
    # === 3. ENTIDADES COMPARTIDAS ===
    write("=" * 70)
    write("BÚSQUEDA DE ENTIDADES COMPARTIDAS:")
    write("-" * 70)
    
    user_refs = 0
    customer_refs = 0
    
    for doc in docs:
        doc_str = json.dumps(doc)
        if 'user' in doc_str.lower() or 'createdby' in doc_str.lower():
            user_refs += 1
        if 'customer' in doc_str.lower():
            customer_refs += 1
    
    write(f"  Docs con referencia a 'user': {user_refs}/{len(docs)}")
    write(f"  Docs con referencia a 'customer': {customer_refs}/{len(docs)}")
    write()
    
    # === 4. CAMPOS JSONB CANDIDATOS ===
    write("=" * 70)
    write("CANDIDATOS A JSONB (estructura variable):")
    write("-" * 70)
    
    jsonb_candidates = []
    for key in sorted(all_keys.keys()):
        # Buscar objetos con estructura variable
        structures = set()
        for doc in docs:
            if key in doc and isinstance(doc[key], dict):
                structures.add(tuple(sorted(doc[key].keys())))
        
        if len(structures) > 1:
            jsonb_candidates.append((key, len(structures)))
    
    if jsonb_candidates:
        for field, variant_count in jsonb_candidates:
            write(f"  {field:35s} {variant_count} estructuras distintas")
    else:
        write("  No se detectaron campos con estructura altamente variable")
    write()
    
    # === 5. TIMESTAMPS ===
    write("=" * 70)
    write("CAMPOS DE TIMESTAMP:")
    write("-" * 70)
    
    timestamp_fields = [k for k in all_keys.keys() if 'at' in k.lower() or 'date' in k.lower()]
    for field in sorted(timestamp_fields):
        count = all_keys[field]
        pct = count * 100 // len(docs)
        write(f"  {field:35s} {count:3d}/{len(docs):3d} ({pct:3d}%)")
    write()
    
    # === 6. DOCUMENTOS COMPLETOS ===
    write("=" * 70)
    write("DOCUMENTOS COMPLETOS (primero, medio, último):")
    write("=" * 70)
    write()
    
    indices = [0, len(docs) // 2, len(docs) - 1]
    for i, idx in enumerate(indices, 1):
        write(f"[Documento {i} - Índice {idx}]")
        write(json.dumps(docs[idx], indent=2, default=str))
        write()
    
    # === 7. RECOMENDACIONES ===
    write("=" * 70)
    write("RECOMENDACIONES PARA SCHEMA POSTGRESQL:")
    write("=" * 70)
    write()
    
    write("TABLA PRINCIPAL (lml_formbuilder.main):")
    write("  ✅ formbuilder_id VARCHAR(255) PRIMARY KEY")
    for key in sorted(all_keys.keys()):
        if key not in ['_id'] and not isinstance(docs[0].get(key), (list, dict)):
            write(f"  • {key}")
    write()
    
    write("TABLAS RELACIONADAS (candidatos - si avg > 5):")
    for field in sorted(array_fields_detected):
        sizes = [len(doc.get(field, [])) for doc in docs if isinstance(doc.get(field), list)]
        if sizes and sum(sizes) / len(sizes) > 5:
            write(f"  → lml_formbuilder.{field}")
    write()
    
    write("CAMPOS JSONB (estructura variable):")
    for field, _ in jsonb_candidates:
        write(f"  → {field} JSONB")
    write()
    
    # Guardar a archivo
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output))
    
    print(f"\n✅ Análisis guardado en: {output_file}")


if __name__ == "__main__":
    analyze_formbuilder()
