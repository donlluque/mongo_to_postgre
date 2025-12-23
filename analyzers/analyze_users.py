# analyze_users.py
"""
Script de análisis estructural para lml_users_mesa4core. 
Descubre automáticamente campos, tipos, catálogos embebidos y relaciones N:M.
"""

import json
from collections import defaultdict
from datetime import datetime

# Configuración
SAMPLE_FILE = 'samples/lml_users_mesa4core_sample.json'

def load_sample():
    """Carga el archivo JSON de sample."""
    try:
        with open(SAMPLE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"[ERROR] Error: No se encontró el archivo {SAMPLE_FILE}")
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
                    'count': 0,
                    'types': set(),
                    'sample_values': []
                }
            
            field_stats[field_name]['count'] += 1
            value = doc.get(field_name)
            
            # Detectar tipo
            if value is None:
                field_type = 'null'
            elif isinstance(value, dict):
                field_type = 'object'
            elif isinstance(value, list):
                field_type = 'array'
            elif isinstance(value, bool):
                field_type = 'boolean'
            elif isinstance(value, int):
                field_type = 'integer'
            elif isinstance(value, float):
                field_type = 'float'
            else:
                field_type = 'string'
            
            field_stats[field_name]['types'].add(field_type)
            
            # Guardar samples (primeros 3 valores únicos)
            if len(field_stats[field_name]['sample_values']) < 3:
                if value not in field_stats[field_name]['sample_values']:
                    field_stats[field_name]['sample_values'].append(value)
    
    # Calcular cobertura porcentual
    for field_name, stats in field_stats.items():
        stats['coverage'] = (stats['count'] / total_docs) * 100
        stats['types'] = list(stats['types'])
    
    return field_stats

def extract_embedded_catalogs(documents):
    """
    Extrae catálogos embebidos (role, area, subarea, position, signaturetype). 
    Retorna dict con valores únicos de cada catálogo.
    """
    catalogs = {
        'roles': {},
        'areas': {},
        'subareas': {},
        'positions': {},
        'signaturetypes': {}
    }
    
    for doc in documents:
        # Role
        role = doc.get('role', {})
        if isinstance(role, dict) and role.get('id'):
            catalogs['roles'][role['id']] = role. get('name', 'N/A')
        
        # Area
        area = doc.get('area', {})
        if isinstance(area, dict) and area.get('id'):
            catalogs['areas'][area['id']] = {
                'name': area.get('name', 'N/A'),
                'descripcion': area.get('descripcion')
            }
        
        # Subarea
        subarea = doc.get('subarea', {})
        if isinstance(subarea, dict) and subarea.get('id'):
            catalogs['subareas'][subarea['id']] = subarea.get('name', 'N/A')
        
        # Position
        position = doc. get('position', {})
        if isinstance(position, dict) and position.get('id'):
            catalogs['positions'][position['id']] = position.get('name', 'N/A')
        
        # Signaturetype
        signaturetype = doc.get('signaturetype', {})
        if isinstance(signaturetype, dict) and signaturetype.get('id'):
            catalogs['signaturetypes'][signaturetype['id']] = {
                'name': signaturetype.get('name', 'N/A'),
                'descripcion': signaturetype.get('descripcion')
            }
    
    return catalogs

def analyze_array_fields(documents):
    """
    Analiza campos de tipo array (privileges, groups).
    Retorna estadísticas de cardinalidad. 
    """
    array_stats = {}
    
    # Detectar todos los campos array
    for doc in documents:
        for field_name, value in doc.items():
            if isinstance(value, list):
                if field_name not in array_stats:
                    array_stats[field_name] = {
                        'lengths': [],
                        'unique_ids': set(),
                        'sample_items': []
                    }
                
                array_stats[field_name]['lengths'].append(len(value))
                
                # Extraer IDs únicos si son objetos con 'id'
                for item in value:
                    if isinstance(item, dict) and 'id' in item:
                        array_stats[field_name]['unique_ids'].add(item['id'])
                        
                        # Guardar sample
                        if len(array_stats[field_name]['sample_items']) < 3:
                            array_stats[field_name]['sample_items'].append({
                                'id': item. get('id'),
                                'name': item.get('name', 'N/A')
                            })
    
    # Calcular estadísticas de cardinalidad
    for field_name, stats in array_stats.items():
        lengths = stats['lengths']
        if lengths:
            stats['min'] = min(lengths)
            stats['max'] = max(lengths)
            stats['avg'] = sum(lengths) / len(lengths)
            stats['total_unique_ids'] = len(stats['unique_ids'])
        
        # Limpiar datos internos
        del stats['lengths']
        del stats['unique_ids']
    
    return array_stats

def analyze_timestamps(documents):
    """
    Analiza los diferentes formatos de timestamp presentes.
    """
    timestamp_fields = ['created_at', 'updated_at', 'createdAt', 'updatedAt']
    timestamp_stats = {}
    
    for field in timestamp_fields:
        count = 0
        types = set()
        samples = []
        
        for doc in documents:
            value = doc.get(field)
            if value is not None:
                count += 1
                
                if isinstance(value, dict):
                    types.add('object (MongoDB Date)')
                    if '$date' in value and len(samples) < 2:
                        samples.append(value['$date'])
                elif isinstance(value, str):
                    types.add('string (ISO)')
                    if len(samples) < 2:
                        samples.append(value)
        
        if count > 0:
            timestamp_stats[field] = {
                'count': count,
                'coverage': (count / len(documents)) * 100,
                'types': list(types),
                'samples': samples
            }
    
    return timestamp_stats

def generate_report(documents, field_stats, catalogs, array_stats, timestamp_stats):
    """Genera reporte legible con recomendaciones."""
    
    print("=" * 80)
    print("ANÁLISIS DE lml_users_mesa4core")
    print("=" * 80)
    print(f"\nTotal de documentos analizados: {len(documents)}\n")
    
    # Campos de primer nivel
    print("-" * 80)
    print("CAMPOS DE PRIMER NIVEL")
    print("-" * 80)
    
    # Ordenar por cobertura descendente
    sorted_fields = sorted(field_stats.items(), key=lambda x: x[1]['coverage'], reverse=True)
    
    for field_name, stats in sorted_fields:
        coverage = stats['coverage']
        types_str = ', '.join(stats['types'])
        print(f"\n{field_name}:")
        print(f"  Cobertura: {coverage:.1f}% ({stats['count']}/{len(documents)} docs)")
        print(f"  Tipos: {types_str}")
        
        # Mostrar samples solo para campos simples
        if 'object' not in stats['types'] and 'array' not in stats['types']:
            samples = stats['sample_values'][:2]
            if samples:
                samples_str = ', '.join([str(s)[:50] for s in samples if s is not None])
                if samples_str:
                    print(f"  Samples: {samples_str}")
    
    # Catálogos embebidos
    print("\n" + "-" * 80)
    print("CATÁLOGOS EMBEBIDOS (para tablas separadas)")
    print("-" * 80)
    
    for catalog_name, catalog_data in catalogs.items():
        print(f"\n{catalog_name}: {len(catalog_data)} valores únicos")
        
        # Mostrar primeros 5
        for idx, (cat_id, cat_value) in enumerate(list(catalog_data.items())[:5]):
            if isinstance(cat_value, dict):
                name = cat_value.get('name', 'N/A')
                print(f"  - {cat_id}: {name}")
            else:
                print(f"  - {cat_id}: {cat_value}")
        
        if len(catalog_data) > 5:
            print(f"  ... y {len(catalog_data) - 5} más")
    
    # Arrays (relaciones N:M)
    print("\n" + "-" * 80)
    print("ARRAYS (relaciones N:M)")
    print("-" * 80)
    
    for field_name, stats in array_stats.items():
        print(f"\n{field_name}:")
        print(f"  Cardinalidad: min={stats['min']}, max={stats['max']}, avg={stats['avg']:.1f}")
        print(f"  IDs únicos encontrados: {stats['total_unique_ids']}")
        
        if stats['sample_items']:
            print(f"  Samples:")
            for item in stats['sample_items']:
                print(f"    - {item['id']}: {item['name']}")
    
    # Timestamps
    print("\n" + "-" * 80)
    print("ANÁLISIS DE TIMESTAMPS")
    print("-" * 80)
    
    for field_name, stats in timestamp_stats.items():
        print(f"\n{field_name}:")
        print(f"  Cobertura: {stats['coverage']:.1f}% ({stats['count']}/{len(documents)} docs)")
        print(f"  Formatos: {', '.join(stats['types'])}")
        if stats['samples']:
            print(f"  Samples: {stats['samples'][0]}")
    
    # Recomendaciones
    print("\n" + "=" * 80)
    print("RECOMENDACIONES PARA SCHEMA PostgreSQL")
    print("=" * 80)
    
    print("\n1.  TABLAS DE CATÁLOGOS:")
    for catalog_name, catalog_data in catalogs.items():
        table_name = f"users. {catalog_name}"
        print(f"   - {table_name} ({len(catalog_data)} registros)")
    
    print("\n2.  RELACIONES N:M:")
    for field_name, stats in array_stats.items():
        if stats['total_unique_ids'] > 0:
            table_name = f"users.user_{field_name}"
            print(f"   - {table_name} (cardinalidad promedio: {stats['avg']:. 1f})")
    
    print("\n3. TIMESTAMPS:")
    print("   Estrategia recomendada:")
    if 'updatedAt' in timestamp_stats and timestamp_stats['updatedAt']['coverage'] > 90:
        print("   - Priorizar 'updatedAt' (formato MongoDB Date)")
        print("   - Usar 'updated_at' como fallback")
    else:
        print("   - Evaluar cuál tiene mayor cobertura")
    
    print("\n4. CAMPOS OPCIONALES:")
    optional_fields = [f for f, s in field_stats.items() if s['coverage'] < 100]
    print(f"   {len(optional_fields)} campos requieren NULL en PostgreSQL:")
    for field in optional_fields[:10]:
        coverage = field_stats[field]['coverage']
        print(f"   - {field} ({coverage:.1f}% cobertura)")
    if len(optional_fields) > 10:
        print(f"   ... y {len(optional_fields) - 10} más")

def main():
    # Cargar datos
    documents = load_sample()
    if not documents:
        return
    
    print(f"[OK] Archivo cargado: {len(documents)} documentos")
    
    # Análisis
    print("[*] Analizando estructura...")
    field_stats = analyze_field_coverage(documents)
    catalogs = extract_embedded_catalogs(documents)
    array_stats = analyze_array_fields(documents)
    timestamp_stats = analyze_timestamps(documents)
    
    # Generar reporte
    generate_report(documents, field_stats, catalogs, array_stats, timestamp_stats)
    
    print("\n" + "=" * 80)
    print("[OK] Análisis completado")
    print("=" * 80)

if __name__ == '__main__':
    main()