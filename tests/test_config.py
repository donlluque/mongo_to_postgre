"""
Test de validación para config.py. 

Verifica que:
- Configuración carga correctamente
- Funciones helper funcionan según especificación
- Manejo de errores es apropiado
"""

import sys
import os

# === RESOLUCIÓN DE PATH ===
# Agrega el directorio raíz del proyecto al path de Python
# __file__ = /ruta/proyecto/tests/test_config.py
# dirname(__file__) = /ruta/proyecto/tests
# dirname(dirname(__file__)) = /ruta/proyecto (raíz)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import config

# === TESTS ===

def test_get_collection_config():
    """Verifica que get_collection_config retorna estructura correcta."""
    print("\n=== TEST 1: get_collection_config ===")
    
    cfg = config.get_collection_config('lml_users_mesa4core')
    
    # Validaciones
    assert 'postgres_schema' in cfg, "Falta key 'postgres_schema'"
    assert cfg['postgres_schema'] == 'lml_users', f"Schema esperado 'lml_users', obtenido '{cfg['postgres_schema']}'"
    assert cfg['collection_type'] == 'truth_source', "lml_users debe ser truth_source"
    
    print(f"✅ Schema: {cfg['postgres_schema']}")
    print(f"✅ Type: {cfg['collection_type']}")
    print(f"✅ Primary key: {cfg['primary_key']}")


def test_validate_migration_order():
    """Verifica que validate_migration_order retorna dependencias correctas."""
    print("\n=== TEST 2: validate_migration_order ===")
    
    # Colección con dependencias
    deps = config. validate_migration_order('lml_processes_mesa4core')
    assert 'lml_users_mesa4core' in deps, "lml_processes debe depender de lml_users"
    print(f"✅ Dependencias de processes: {deps}")
    
    # Colección sin dependencias
    deps_users = config.validate_migration_order('lml_users_mesa4core')
    assert deps_users == [], "lml_users no debe tener dependencias"
    print(f"✅ Dependencias de users: {deps_users} (vacío como esperado)")


def test_is_truth_source():
    """Verifica que is_truth_source distingue correctamente tipos."""
    print("\n=== TEST 3: is_truth_source ===")
    
    # Truth sources
    assert config.is_truth_source('lml_users_mesa4core') == True
    print(f"✅ lml_users es truth_source: True")
    
    assert config. is_truth_source('lml_usersgroups_mesa4core') == True
    print(f"✅ lml_usersgroups es truth_source: True")
    
    # Consumers
    assert config.is_truth_source('lml_processes_mesa4core') == False
    print(f"✅ lml_processes es consumer: False")


def test_get_schema_for_collection():
    """Verifica shortcut para obtener schema."""
    print("\n=== TEST 4: get_schema_for_collection ===")
    
    schema = config.get_schema_for_collection('lml_usersgroups_mesa4core')
    assert schema == 'lml_usersgroups'
    print(f"✅ Schema de usersgroups: {schema}")


def test_error_handling():
    """Verifica que errores se manejan apropiadamente."""
    print("\n=== TEST 5: Error handling ===")
    
    try:
        config.get_collection_config('coleccion_inexistente')
        assert False, "Debería lanzar KeyError"
    except KeyError as e:
        assert 'coleccion_inexistente' in str(e)
        assert 'disponibles' in str(e). lower()
        print(f"✅ Error manejado correctamente")
        print(f"   Mensaje: {str(e)[:80]}...")


def test_migration_order_integrity():
    """Verifica que MIGRATION_ORDER respeta todas las dependencias."""
    print("\n=== TEST 6: Integridad de MIGRATION_ORDER ===")
    
    processed = set()
    
    for collection in config.MIGRATION_ORDER:
        deps = config.validate_migration_order(collection)
        
        # Todas las dependencias deben haber sido procesadas antes
        for dep in deps:
            assert dep in processed, f"{collection} requiere {dep}, pero {dep} aparece después en MIGRATION_ORDER"
        
        processed.add(collection)
    
    print(f"✅ MIGRATION_ORDER respeta todas las dependencias")
    print(f"   Orden: {' → '.join(config.MIGRATION_ORDER)}")


# === EJECUCIÓN ===

if __name__ == '__main__':
    print("=" * 70)
    print("🧪 TESTS DE VALIDACIÓN: config.py")
    print("=" * 70)
    
    tests = [
        test_get_collection_config,
        test_validate_migration_order,
        test_is_truth_source,
        test_get_schema_for_collection,
        test_error_handling,
        test_migration_order_integrity
    ]
    
    failed = 0
    
    for test_func in tests:
        try:
            test_func()
        except AssertionError as e:
            print(f"\n❌ FALLO: {test_func.__name__}")
            print(f"   {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ ERROR: {test_func.__name__}")
            print(f"   {type(e).__name__}: {e}")
            failed += 1
    
    print("\n" + "=" * 70)
    
    if failed == 0:
        print("✅ TODOS LOS TESTS PASARON")
        print("=" * 70)
        sys.exit(0)
    else:
        print(f"❌ {failed} TEST(S) FALLARON")
        print("=" * 70)
        sys.exit(1)