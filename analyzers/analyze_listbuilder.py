"""
Script de análisis profundo para el json de lml_listbuilder 
y generar un txt complementario para analisis
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def analyze_listbuilder():
    filepath = Path("samples/lml_listbuilder_mesa4core_sample.json")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        docs = json.load(f)
    
    print(f"{'='*70}")
    print(f"ANÁLISIS ESTRUCTURAL: lml_listbuilder_mesa4core")
    print(f"{'='*70}\n")
    
    print(f"📊 Total documentos: {len(docs)}\n")
    
    # 1. Campos de primer nivel
    all_keys = Counter()
    for doc in docs:
        all_keys.update(doc.keys())
    
    print("CAMPOS DE PRIMER NIVEL:")
    print("-" * 70)
    for key, count in sorted(all_keys.items()):
        pct = count * 100 // len(docs)
        print(f"  {key:35s} {count:3d}/{len(docs):3d} ({pct:3d}%)")
    
    # 2. Analizar arrays (candidatos a tablas relacionadas)
    print(f"\n{'='*70}")
    print("ARRAYS (cardinalidad):")
    print("-" * 70)
    
    array_fields = [
        'lmPathActions', 'lmModalActions', 'buttonLinks',
        'fields', 'allAvailableFields', 'items',
        'searchOnFieldsSelected', 'searchOnFieldsToSelected'
    ]
    
    for field in array_fields:
        sizes = []
        for doc in docs:
            if field in doc and isinstance(doc[field], list):
                sizes.append(len(doc[field]))
        
        if sizes:
            avg = sum(sizes) / len(sizes)
            print(f"  {field:35s} Avg: {avg:5.1f}  Min: {min(sizes):3d}  Max: {max(sizes):3d}")
        else:
            print(f"  {field:35s} (no presente)")
    
    # 3. Buscar referencias a users/customers
    print(f"\n{'='*70}")
    print("BÚSQUEDA DE ENTIDADES COMPARTIDAS:")
    print("-" * 70)
    
    user_refs = []
    customer_refs = []
    
    for doc in docs:
        doc_str = json.dumps(doc)
        if 'user' in doc_str.lower() or 'createdby' in doc_str.lower():
            user_refs.append(doc.get('_id', {}).get('$oid', 'unknown'))
        if 'customer' in doc_str.lower():
            customer_refs.append(doc.get('_id', {}).get('$oid', 'unknown'))
    
    print(f"  Docs con referencia a 'user': {len(user_refs)}/{len(docs)}")
    print(f"  Docs con referencia a 'customer': {len(customer_refs)}/{len(docs)}")
    
    # 4. Mostrar estructura de 3 documentos completos
    print(f"\n{'='*70}")
    print("DOCUMENTOS COMPLETOS (primero, medio, último):")
    print("=" * 70)
    
    indices = [0, len(docs) // 2, len(docs) - 1]
    for i, idx in enumerate(indices, 1):
        print(f"\n[Documento {i} - Índice {idx}]")
        print(json.dumps(docs[idx], indent=2, default=str))
        print()
    
    # 5. Análisis de valores únicos en campos clave
    print(f"{'='*70}")
    print("VALORES ÚNICOS EN CAMPOS CLAVE:")
    print("-" * 70)
    
    key_fields = ['alias', 'titleList', 'gqlField']
    for field in key_fields:
        values = set()
        for doc in docs:
            if field in doc:
                values.add(doc[field])
        print(f"  {field:20s} {len(values)} valores únicos")
        if len(values) <= 10:  # Mostrar si hay pocos
            for val in sorted(values):
                print(f"    - {val}")

if __name__ == "__main__":
    analyze_listbuilder()