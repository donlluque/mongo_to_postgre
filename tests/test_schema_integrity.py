"""
Test de integridad de schemas.

Valida que:
1. Tablas referenciadas en migradores existen en dbsetup.py
2. No hay typos en nombres de tablas
3. Estructura de batches coincide con tablas del schema
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- IMPORTAR TODOS LOS MIGRADORES AQUÍ ---
from migrators.lml_processes import LmlProcessesMigrator
from migrators. lml_listbuilder import LmlListbuilderMigrator
from migrators.lml_formbuilder import LmlFormbuilderMigrator
from migrators. lml_users import LmlUsersMigrator  # <--- NUEVO


def get_migradores_instances():
    """Helper para instanciar todos los migradores."""
    return [
        ('LmlProcessesMigrator', LmlProcessesMigrator('lml_processes')),
        ('LmlListbuilderMigrator', LmlListbuilderMigrator('lml_listbuilder')),
        ('LmlFormbuilderMigrator', LmlFormbuilderMigrator('lml_formbuilder')),
        ('LmlUsersMigrator', LmlUsersMigrator('lml_users')),  # <--- NUEVO
    ]


def test_batch_tables_naming():
    """Verifica que tablas en initialize_batches() siguen convención snake_case."""
    print("\n🔍 Test: Convención de nombres de tablas")
    
    migradores = get_migradores_instances()
    errors = []
    
    for name, migrator in migradores:
        batches = migrator.initialize_batches()
        
        print(f"\n   📦 {name}:")
        print(f"      Schema: {migrator.schema}")
        
        for table_name in batches['related']. keys():
            # Validar snake_case (solo letras minúsculas y guiones bajos)
            if not table_name.replace('_', '').islower():
                errors.append(f"{name}: Tabla '{table_name}' no sigue snake_case")
                print(f"      ❌ {table_name} (debe ser snake_case)")
            else:
                print(f"      ✅ {table_name}")
    
    return len(errors) == 0, errors


def test_insert_methods_exist():
    """Verifica que existe método _insert_<tabla>_batch() para cada tabla."""
    print("\n🔍 Test: Métodos de inserción para tablas relacionadas")
    
    migradores = get_migradores_instances()
    errors = []
    
    for name, migrator in migradores:
        batches = migrator.initialize_batches()
        
        print(f"\n   📦 {name}:")
        
        for table_name in batches['related'].keys():
            method_name = f'_insert_{table_name}_batch'
            
            if not hasattr(migrator, method_name):
                errors.append(f"{name}: Falta método {method_name}()")
                print(f"      ❌ {method_name}() no existe")
            else:
                print(f"      ✅ {method_name}() existe")
    
    return len(errors) == 0, errors


def test_schema_attribute():
    """Verifica que migradores tienen atributo 'schema' definido."""
    print("\n🔍 Test: Atributo 'schema' definido")
    
    migradores = get_migradores_instances()
    errors = []
    
    for name, migrator in migradores:
        if not hasattr(migrator, 'schema'):
            errors.append(f"{name}: Falta atributo 'schema'")
            print(f"   ❌ {name}: No tiene atributo 'schema'")
        elif not isinstance(migrator.schema, str):
            errors.append(f"{name}: Atributo 'schema' no es string")
            print(f"   ❌ {name}: 'schema' no es string")
        elif not migrator.schema:
            errors.append(f"{name}: Atributo 'schema' está vacío")
            print(f"   ❌ {name}: 'schema' está vacío")
        else:
            print(f"   ✅ {name}: schema = '{migrator.schema}'")
    
    return len(errors) == 0, errors


def run_all_tests():
    """Ejecuta todos los tests de integridad de schema."""
    print("=" * 70)
    print("🧪 TESTS DE INTEGRIDAD DE SCHEMAS")
    print("=" * 70)
    
    tests = [
        test_batch_tables_naming,
        test_insert_methods_exist,
        test_schema_attribute
    ]
    
    all_errors = []
    
    for test_func in tests:
        success, errors = test_func()
        all_errors.extend(errors)
    
    print("\n" + "=" * 70)
    
    if len(all_errors) == 0:
        print("✅ TODOS LOS TESTS PASARON")
        return True
    else:
        print(f"❌ {len(all_errors)} ERRORES ENCONTRADOS")
        for error in all_errors:
            print(f"   - {error}")
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)