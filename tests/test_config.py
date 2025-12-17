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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

# === HELPERS DINÁMICOS ===


def get_all_collections():
    """Retorna lista de todas las colecciones configuradas."""
    return list(config.COLLECTIONS.keys())


def get_truth_source_collections():
    """Retorna solo colecciones truth_source."""
    return [
        name
        for name, cfg in config.COLLECTIONS.items()
        if cfg.get("collection_type") == "truth_source"
    ]


def get_consumer_collections():
    """Retorna solo colecciones consumer."""
    return [
        name
        for name, cfg in config.COLLECTIONS.items()
        if cfg.get("collection_type") == "consumer"
    ]


# === TESTS ===


def test_get_collection_config():
    """Verifica que get_collection_config retorna estructura correcta para TODAS las colecciones."""
    print("\n=== TEST 1: get_collection_config ===")

    all_collections = get_all_collections()
    errors = []

    for collection_name in all_collections:
        cfg = config.get_collection_config(collection_name)

        # Validar que tenga las keys requeridas
        required_keys = [
            "postgres_schema",
            "primary_key",
            "collection_type",
            "depends_on",
            "description",
        ]
        for key in required_keys:
            if key not in cfg:
                errors.append(f"{collection_name}: Falta key '{key}'")

        # Validar tipos
        if not isinstance(cfg.get("postgres_schema"), str):
            errors.append(f"{collection_name}: postgres_schema debe ser string")

        if not isinstance(cfg.get("depends_on"), list):
            errors.append(f"{collection_name}: depends_on debe ser lista")

        if cfg.get("collection_type") not in ["truth_source", "consumer"]:
            errors.append(
                f"{collection_name}: collection_type debe ser 'truth_source' o 'consumer'"
            )

    if errors:
        for error in errors:
            print(f"   ❌ {error}")
        raise AssertionError(f"Errores en configuración: {errors}")

    print(
        f"✅ Todas las {len(all_collections)} colecciones tienen configuración válida"
    )
    for collection_name in all_collections:
        cfg = config.get_collection_config(collection_name)
        print(
            f"   • {collection_name} → {cfg['postgres_schema']} ({cfg['collection_type']})"
        )


def test_validate_migration_order():
    """Verifica que validate_migration_order retorna dependencias correctas."""
    print("\n=== TEST 2: validate_migration_order ===")

    # Test con consumers (deben tener dependencias)
    consumers = get_consumer_collections()
    for collection_name in consumers:
        deps = config.validate_migration_order(collection_name)
        if not deps:
            print(
                f"   ⚠️  {collection_name} es consumer pero no tiene dependencias (revisar si es correcto)"
            )
        else:
            print(f"   ✅ {collection_name} depende de: {deps}")

    # Test con truth_sources (NO deben tener dependencias, excepto casos especiales)
    truth_sources = get_truth_source_collections()
    for collection_name in truth_sources:
        deps = config.validate_migration_order(collection_name)
        if deps:
            # Esto es válido si un truth_source depende de otro truth_source
            print(f"   ℹ️  {collection_name} (truth_source) depende de: {deps}")
        else:
            print(f"   ✅ {collection_name} sin dependencias (como esperado)")


def test_is_truth_source():
    """Verifica que is_truth_source distingue correctamente tipos."""
    print("\n=== TEST 3: is_truth_source ===")

    # Verificar todos los truth_sources
    truth_sources = get_truth_source_collections()
    for collection_name in truth_sources:
        assert config.is_truth_source(collection_name) == True
        print(f"   ✅ {collection_name} es truth_source: True")

    # Verificar todos los consumers
    consumers = get_consumer_collections()
    for collection_name in consumers:
        assert config.is_truth_source(collection_name) == False
        print(f"   ✅ {collection_name} es consumer: False")


def test_get_schema_for_collection():
    """Verifica shortcut para obtener schema de TODAS las colecciones."""
    print("\n=== TEST 4: get_schema_for_collection ===")

    all_collections = get_all_collections()

    for collection_name in all_collections:
        cfg = config.get_collection_config(collection_name)
        expected_schema = cfg["postgres_schema"]
        actual_schema = config.get_schema_for_collection(collection_name)

        assert (
            actual_schema == expected_schema
        ), f"{collection_name}: esperado '{expected_schema}', obtenido '{actual_schema}'"

        print(f"   ✅ {collection_name} → {actual_schema}")


def test_error_handling():
    """Verifica que errores se manejan apropiadamente."""
    print("\n=== TEST 5: Error handling ===")

    try:
        config.get_collection_config("coleccion_inexistente")
        assert False, "Debería lanzar KeyError"
    except KeyError as e:
        assert "coleccion_inexistente" in str(e)
        assert "disponibles" in str(e).lower()
        print(f"✅ Error manejado correctamente")
        print(f"   Mensaje: {str(e)[:80]}...")


def test_migration_order_integrity():
    """Verifica que MIGRATION_ORDER respeta todas las dependencias."""
    print("\n=== TEST 6: Integridad de MIGRATION_ORDER ===")

    processed = set()
    errors = []

    for collection in config.MIGRATION_ORDER:
        deps = config.validate_migration_order(collection)

        # Todas las dependencias deben haber sido procesadas antes
        for dep in deps:
            if dep not in processed:
                errors.append(
                    f"{collection} requiere {dep}, pero {dep} aparece después en MIGRATION_ORDER"
                )

        processed.add(collection)

    if errors:
        for error in errors:
            print(f"   ❌ {error}")
        raise AssertionError(f"Errores en MIGRATION_ORDER: {errors}")

    print(f"✅ MIGRATION_ORDER respeta todas las dependencias")
    print(f"   Orden: {' → '.join(config.MIGRATION_ORDER)}")


def test_all_collections_in_migration_order():
    """Verifica que todas las colecciones configuradas estén en MIGRATION_ORDER."""
    print("\n=== TEST 7: Completitud de MIGRATION_ORDER ===")

    all_collections = set(get_all_collections())
    migration_order_set = set(config.MIGRATION_ORDER)

    # Colecciones configuradas pero NO en MIGRATION_ORDER
    missing = all_collections - migration_order_set
    if missing:
        print(f"   ❌ Colecciones configuradas pero NO en MIGRATION_ORDER: {missing}")
        raise AssertionError(f"Agregar {missing} a MIGRATION_ORDER")

    # Colecciones en MIGRATION_ORDER pero NO configuradas
    extra = migration_order_set - all_collections
    if extra:
        print(f"   ❌ Colecciones en MIGRATION_ORDER pero NO configuradas: {extra}")
        raise AssertionError(
            f"Configurar {extra} en COLLECTIONS o remover de MIGRATION_ORDER"
        )

    print(f"✅ Todas las {len(all_collections)} colecciones están en MIGRATION_ORDER")


# === EJECUCIÓN ===

if __name__ == "__main__":
    print("=" * 70)
    print("🧪 TESTS DE VALIDACIÓN: config.py")
    print("=" * 70)

    tests = [
        test_get_collection_config,
        test_validate_migration_order,
        test_is_truth_source,
        test_get_schema_for_collection,
        test_error_handling,
        test_migration_order_integrity,
        test_all_collections_in_migration_order,  # ← NUEVO TEST
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
