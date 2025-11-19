"""
Test de interfaz para migradores.

Valida que todos los migradores:
1. Heredan de BaseMigrator
2. Implementan métodos requeridos con firmas correctas
3. Retornan estructuras de datos esperadas
"""

import sys
import os
import inspect

# Agregar project root al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrators.base import BaseMigrator
from migrators.lml_processes import LmlProcessesMigrator
from migrators.lml_listbuilder import LmlListbuilderMigrator


def test_migrator_inheritance():
    """
    Verifica que todos los migradores heredan de BaseMigrator.
    
    Concepto: Herencia garantiza que todos los migradores tienen
    la misma interfaz pública, permitiendo polimorfismo en mongomigra.py
    """
    print("\n🔍 Test 1: Herencia de BaseMigrator")
    
    migradores = [
        ('LmlProcessesMigrator', LmlProcessesMigrator),
        ('LmlListbuilderMigrator', LmlListbuilderMigrator),
    ]
    
    errors = []
    
    for name, migrator_class in migradores:
        if not issubclass(migrator_class, BaseMigrator):
            errors.append(f"{name} no hereda de BaseMigrator")
            print(f"   ❌ {name}")
        else:
            print(f"   ✅ {name} hereda de BaseMigrator")
    
    return len(errors) == 0, errors


def test_required_methods():
    """
    Verifica que migradores implementan métodos abstractos.
    
    Métodos requeridos por BaseMigrator:
    - initialize_batches()
    - extract_shared_entities()
    - extract_data()
    - insert_batches()
    """
    print("\n🔍 Test 2: Implementación de métodos requeridos")
    
    required_methods = [
        'initialize_batches',
        'extract_shared_entities',
        'extract_data',
        'insert_batches'
    ]
    
    migradores = [
        ('LmlProcessesMigrator', LmlProcessesMigrator),
        ('LmlListbuilderMigrator', LmlListbuilderMigrator),
    ]
    
    errors = []
    
    for name, migrator_class in migradores:
        print(f"\n   📦 {name}:")
        
        for method_name in required_methods:
            if not hasattr(migrator_class, method_name):
                errors.append(f"{name} no implementa {method_name}()")
                print(f"      ❌ {method_name}()")
            else:
                method = getattr(migrator_class, method_name)
                
                # Verificar que no es el método abstracto de la base
                if method.__qualname__.startswith('BaseMigrator'):
                    errors.append(f"{name}.{method_name}() no está implementado (usa abstracto)")
                    print(f"      ❌ {method_name}() (abstracto)")
                else:
                    print(f"      ✅ {method_name}()")
    
    return len(errors) == 0, errors


def test_initialize_batches_structure():
    """
    Verifica que initialize_batches() retorna estructura correcta.
    
    Estructura esperada:
    {
        'main': [],
        'related': {
            'tabla1': [],
            'tabla2': []
        }
    }
    """
    print("\n🔍 Test 3: Estructura de batches")
    
    migradores = [
        ('LmlProcessesMigrator', LmlProcessesMigrator('lml_processes')),
        ('LmlListbuilderMigrator', LmlListbuilderMigrator('lml_listbuilder')),
    ]
    
    errors = []
    
    for name, migrator in migradores:
        batches = migrator.initialize_batches()
        
        # Validar estructura
        if not isinstance(batches, dict):
            errors.append(f"{name}.initialize_batches() no retorna dict")
            print(f"   ❌ {name}: No retorna dict")
            continue
        
        if 'main' not in batches:
            errors.append(f"{name}.initialize_batches() no tiene key 'main'")
            print(f"   ❌ {name}: Falta key 'main'")
        
        if 'related' not in batches:
            errors.append(f"{name}.initialize_batches() no tiene key 'related'")
            print(f"   ❌ {name}: Falta key 'related'")
        
        if not isinstance(batches.get('related'), dict):
            errors.append(f"{name}.initialize_batches()['related'] no es dict")
            print(f"   ❌ {name}: 'related' no es dict")
        
        if len(errors) == 0:
            print(f"   ✅ {name}: Estructura correcta")
            print(f"      - main: list")
            print(f"      - related: dict con {len(batches['related'])} tablas")
    
    return len(errors) == 0, errors


def test_method_signatures():
    """
    Verifica que métodos tienen firmas (parámetros) correctas.
    
    Firmas esperadas:
    - extract_shared_entities(doc, cursor, caches) → dict
    - extract_data(doc, shared_entities) → dict
    - insert_batches(batches, cursor) → None
    """
    print("\n🔍 Test 4: Firmas de métodos")
    
    migradores = [
        ('LmlProcessesMigrator', LmlProcessesMigrator),
        ('LmlListbuilderMigrator', LmlListbuilderMigrator),
    ]
    
    expected_signatures = {
        'extract_shared_entities': ['self', 'doc', 'cursor', 'caches'],
        'extract_data': ['self', 'doc', 'shared_entities'],
        'insert_batches': ['self', 'batches', 'cursor']
    }
    
    errors = []
    
    for name, migrator_class in migradores:
        print(f"\n   📦 {name}:")
        
        for method_name, expected_params in expected_signatures.items():
            method = getattr(migrator_class, method_name)
            sig = inspect.signature(method)
            actual_params = list(sig.parameters.keys())
            
            if actual_params != expected_params:
                errors.append(f"{name}.{method_name}() tiene firma incorrecta")
                print(f"      ❌ {method_name}{sig}")
                print(f"         Esperado: {expected_params}")
                print(f"         Actual: {actual_params}")
            else:
                print(f"      ✅ {method_name}{sig}")
    
    return len(errors) == 0, errors


def run_all_tests():
    """Ejecuta todos los tests de interfaz."""
    print("=" * 70)
    print("🧪 TESTS DE INTERFAZ DE MIGRADORES")
    print("=" * 70)
    
    tests = [
        test_migrator_inheritance,
        test_required_methods,
        test_initialize_batches_structure,
        test_method_signatures
    ]
    
    all_errors = []
    
    for test_func in tests:
        success, errors = test_func()
        all_errors.extend(errors)
    
    print("\n" + "=" * 70)
    
    if len(all_errors) == 0:
        print("✅ TODOS LOS TESTS PASARON")
        print("=" * 70)
        return True
    else:
        print(f"❌ {len(all_errors)} ERRORES ENCONTRADOS")
        print("=" * 70)
        for error in all_errors:
            print(f"   - {error}")
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)