# analyze_usergroups.py
"""
Script de análisis estructural para lml_usersgroups_mesa4core. 
Analiza grupos, sus miembros, y la relación N:M con usuarios.
"""

import json
from collections import defaultdict

# Configuración
SAMPLE_FILE = 'samples/lml_usersgroups_mesa4core_sample.json'

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
                    # Para arrays, guardar longitud en vez del array completo
                    if isinstance(value, list):
                        field_stats[field_name]['sample_values'].append(f"array[{len(value)}]")
                    elif isinstance(value, dict):
                        field_stats[field_name]['sample_values'].append("object{... }")
                    else:
                        field_stats[field_name]['sample_values'].append(value)
    
    # Calcular cobertura porcentual
    for field_name, stats in field_stats.items():
        stats['coverage'] = (stats['count'] / total_docs) * 100
        stats['types'] = list(stats['types'])
    
    return field_stats

def analyze_users_array(documents):
    """
    Analiza el array 'users' que contiene IDs de miembros del grupo.
    Retorna estadísticas de la relación N:M.
    """
    stats = {
        'total_groups': len(documents),
        'groups_with_users': 0,
        'total_memberships': 0,  # Total de relaciones user-group
        'unique_user_ids': set(),
        'user_counts': [],  # Cantidad de usuarios por grupo
        'groups_by_user_count': defaultdict(int),  # Distribución
        'sample_groups': []
    }
    
    for doc in documents:
        users_array = doc.get('users', [])
        
        if users_array:
            stats['groups_with_users'] += 1
            user_count = len(users_array)
            stats['user_counts'].append(user_count)
            stats['total_memberships'] += user_count
            
            # Contar usuarios únicos
            for user_id in users_array:
                stats['unique_user_ids'].add(user_id)
            
            # Distribución por tamaño
            if user_count <= 5:
                bucket = '1-5 usuarios'
            elif user_count <= 10:
                bucket = '6-10 usuarios'
            elif user_count <= 20:
                bucket = '11-20 usuarios'
            else:
                bucket = '20+ usuarios'
            
            stats['groups_by_user_count'][bucket] += 1
            
            # Guardar sample
            if len(stats['sample_groups']) < 3:
                stats['sample_groups'].append({
                    'name': doc.get('name', 'N/A'),
                    'user_count': user_count,
                    'sample_user_ids': users_array[:2]  # Primeros 2 IDs
                })
    
    # Estadísticas de cardinalidad
    if stats['user_counts']:
        stats['min_users'] = min(stats['user_counts'])
        stats['max_users'] = max(stats['user_counts'])
        stats['avg_users'] = sum(stats['user_counts']) / len(stats['user_counts'])
    
    stats['unique_user_count'] = len(stats['unique_user_ids'])
    
    # Limpiar datos internos
    del stats['unique_user_ids']
    del stats['user_counts']
    
    return stats

def analyze_embedded_snapshots(documents):
    """
    Analiza snapshots embebidos en createdBy/updatedBy.
    Detecta qué campos de usuario están presentes en estos snapshots.
    """
    snapshot_fields = defaultdict(int)
    total_snapshots = 0
    
    for doc in documents:
        for snapshot_key in ['createdBy', 'updatedBy']:
            snapshot = doc.get(snapshot_key, {})
            user_snapshot = snapshot.get('user', {})
            
            if user_snapshot:
                total_snapshots += 1
                for field_name in user_snapshot. keys():
                    snapshot_fields[field_name] += 1
    
    # Calcular cobertura
    snapshot_stats = {}
    for field_name, count in snapshot_fields.items():
        snapshot_stats[field_name] = {
            'count': count,
            'coverage': (count / total_snapshots * 100) if total_snapshots > 0 else 0
        }
    
    return snapshot_stats, total_snapshots

def analyze_timestamps(documents):
    """
    Analiza los diferentes formatos de timestamp presentes.
    """
    timestamp_fields = ['createdAt', 'updatedAt']
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

def generate_report(documents, field_stats, users_stats, snapshot_stats, total_snapshots, timestamp_stats):
    """Genera reporte legible con recomendaciones."""
    
    print("=" * 80)
    print("ANÁLISIS DE lml_usersgroups_mesa4core")
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
        
        # Mostrar samples
        if stats['sample_values']:
            samples_str = ', '.join([str(s)[:50] for s in stats['sample_values'] if s is not None])
            if samples_str:
                print(f"  Samples: {samples_str}")
    
    # Análisis del array users (relación N:M)
    print("\n" + "-" * 80)
    print("ANÁLISIS DE MEMBRESÍAS (array 'users')")
    print("-" * 80)
    
    print(f"\nGrupos totales: {users_stats['total_groups']}")
    print(f"Grupos con usuarios: {users_stats['groups_with_users']}")
    print(f"Total de relaciones user-group: {users_stats['total_memberships']}")
    print(f"Usuarios únicos encontrados: {users_stats['unique_user_count']}")
    
    if 'min_users' in users_stats:
        print(f"\nCardinalidad de usuarios por grupo:")
        print(f"  Min: {users_stats['min_users']}")
        print(f"  Max: {users_stats['max_users']}")
        print(f"  Promedio: {users_stats['avg_users']:.1f}")
    
    print(f"\nDistribución por tamaño de grupo:")
    for bucket, count in sorted(users_stats['groups_by_user_count'].items()):
        print(f"  {bucket}: {count} grupos")
    
    print(f"\nSamples de grupos:")
    for sample in users_stats['sample_groups']:
        print(f"  - '{sample['name']}': {sample['user_count']} usuarios")
        print(f"    IDs: {', '.join(sample['sample_user_ids'])}")
    
    # Snapshots embebidos
    print("\n" + "-" * 80)
    print("SNAPSHOTS DE USUARIO (createdBy/updatedBy)")
    print("-" * 80)
    
    print(f"\nTotal de snapshots analizados: {total_snapshots}")
    print(f"Campos encontrados en snapshots:")
    
    # Ordenar por cobertura
    sorted_snapshot_fields = sorted(snapshot_stats.items(), key=lambda x: x[1]['coverage'], reverse=True)
    for field_name, stats in sorted_snapshot_fields[:15]:  # Primeros 15
        print(f"  - {field_name}: {stats['coverage']:.1f}% cobertura")
    
    if len(snapshot_stats) > 15:
        print(f"  ... y {len(snapshot_stats) - 15} campos más")
    
    # Timestamps
    print("\n" + "-" * 80)
    print("ANÁLISIS DE TIMESTAMPS")
    print("-" * 80)
    
    for field_name, stats in timestamp_stats.items():
        print(f"\n{field_name}:")
        print(f"  Cobertura: {stats['coverage']:.1f}% ({stats['count']}/{len(documents)} docs)")
        print(f"  Formatos: {', '.join(stats['types'])}")
        if stats['samples']:
            print(f"  Sample: {stats['samples'][0]}")
    
    # Recomendaciones
    print("\n" + "=" * 80)
    print("RECOMENDACIONES PARA SCHEMA PostgreSQL")
    print("=" * 80)
    
    print("\n1.  SCHEMA user_groups:")
    print("   - user_groups.main (catálogo de grupos)")
    print(f"     Columnas: id, name, alias, deleted, customer_id, created_at, updated_at")
    
    print("\n2. TABLA DE RELACIÓN N:M:")
    print("   - user_groups.members (group_id, user_id)")
    print(f"     Estimado de registros: {users_stats['total_memberships']}")
    print(f"     Usuarios únicos: {users_stats['unique_user_count']}")
    print(f"     Cardinalidad promedio: {users_stats. get('avg_users', 0):.1f} usuarios por grupo")
    
    print("\n3. ESTRATEGIA DE MIGRACIÓN:")
    print("   - Migrar desde lml_usersgroups (no desde lml_users)")
    print("   - DELETE + INSERT por grupo (para sincronizar membresías)")
    print("   - Validar que todos los user_ids existen en users. main (FK)")
    
    print("\n4. CAMPOS OPCIONALES:")
    optional_fields = [f for f, s in field_stats.items() if s['coverage'] < 100]
    if optional_fields:
        print(f"   {len(optional_fields)} campos requieren NULL en PostgreSQL:")
        for field in optional_fields[:10]:
            coverage = field_stats[field]['coverage']
            print(f"   - {field} ({coverage:.1f}% cobertura)")
    
    print("\n5. SNAPSHOTS (createdBy/updatedBy):")
    print("   - NO migrar snapshots completos")
    print("   - Solo extraer: created_by_user_id, updated_by_user_id")
    print("   - Los snapshots son auditoría histórica (metadata)")

def main():
    # Cargar datos
    documents = load_sample()
    if not documents:
        return
    
    print(f"[OK] Archivo cargado: {len(documents)} documentos")
    
    # Análisis
    print("[*] Analizando estructura...")
    field_stats = analyze_field_coverage(documents)
    users_stats = analyze_users_array(documents)
    snapshot_stats, total_snapshots = analyze_embedded_snapshots(documents)
    timestamp_stats = analyze_timestamps(documents)
    
    # Generar reporte
    generate_report(documents, field_stats, users_stats, snapshot_stats, total_snapshots, timestamp_stats)
    
    print("\n" + "=" * 80)
    print("[OK] Análisis completado")
    print("=" * 80)

if __name__ == '__main__':
    main()