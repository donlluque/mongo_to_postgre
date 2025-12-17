# Context: Sistema de Migración MongoDB → PostgreSQL

**Última actualización:** 2025-12-17  
**Estado del proyecto:** En desarrollo activo (7/~8 colecciones migradas)  
**Propósito de este documento:** Continuidad técnica y de metodología de trabajo

---

## 📖 Tabla de Contenidos

1. [Cómo Usar Este Documento](#cómo-usar-este-documento)
2. [Filosofía de Trabajo](#filosofía-de-trabajo)
3. [Estado Actual del Proyecto](#estado-actual-del-proyecto)
4. [Arquitectura Técnica](#arquitectura-técnica)
5. [Decisiones Técnicas](#decisiones-técnicas)
6. [Estructura de Código](#estructura-de-código)
7. [Convenciones y Patrones](#convenciones-y-patrones)
8. [Testing](#testing)
9. [Workflow de Migración](#workflow-de-migración)
10. [Troubleshooting](#troubleshooting)
11. [Mejoras Futuras](#mejoras-futuras)

---

## Cómo Usar Este Documento

Este documento es la **memoria técnica del proyecto**. Su propósito es triple:

1. **Para Asistentes IA**: Entender el contexto completo sin necesidad de explorar todo el código
2. **Para Desarrolladores**: Referencia rápida de decisiones, patrones y convenciones
3. **Para Continuidad**: Permitir que cualquier persona retome el trabajo sin perder el hilo

### Convenciones de Formato

- ✅ = Completado/Implementado
- ⚠️ = Atención/Cuidado requerido
- 🔧 = En progreso/trabajo activo
- 📊 = Métricas/datos medidos
- 💡 = Insight/decisión importante
- 🚫 = Anti-patrón/no hacer

---

## Filosofía de Trabajo

### Estilo de Comunicación

**Tono**: Técnico-pedagógico, profesional pero accesible.

**Principios**:
- Explicar el "por qué", no solo el "qué" y "cómo"
- Documentar trade-offs de cada decisión importante
- Usar ejemplos concretos del proyecto (no genéricos)
- No ser condescendiente: crítica constructiva y técnica

### Metodología de Resolución

**Flujo estándar para agregar una colección** (4 fases):

1. **Análisis** (30-40% del tiempo)
   - Exportar sample: `python export_sample.py <collection> 200`
   - Crear `analyze_<collection>.py` personalizado
   - Identificar: tipos de documentos, campos anidados, catálogos embebidos
   - Decidir: tablas vs JSONB, normalización, claves foráneas

2. **Diseño** (20-30% del tiempo)
   - Actualizar `config.py`: agregar colección con dependencias
   - Diseñar schema en `dbsetup.py`: tablas, FKs, índices
   - Mapear campos MongoDB → PostgreSQL

3. **Implementación** (30-40% del tiempo)
   - Crear migrador heredando de `BaseMigrator`
   - Implementar métodos requeridos (extract_*, insert_*, etc)
   - Testing iterativo con subconjuntos

4. **Validación** (10% del tiempo)
   - Ejecutar suite de tests: `python tests/run_tests.py`
   - Verificar conteos: MongoDB vs PostgreSQL
   - Validar integridad referencial y consultas

---

## Estado Actual del Proyecto

### Visión General

Sistema de migración desde MongoDB (`mesa4core`) a PostgreSQL (`mesamongo`).  
**Objetivo**: Transformar documentos NoSQL anidados en modelo relacional normalizado.

### Razones de la Migración

1. **Integridad de Datos**: Implementar integridad referencial mediante FKs
2. **Normalización**: Eliminar duplicación de datos del modelo desnormalizado
3. **Consultas Complejas**: Habilitar JOINs eficientes y consultas relacionales
4. **Estandarización**: Consolidar entidades compartidas en única fuente de verdad

### Colecciones Migradas

| # | Colección | Schema | Tipo | Docs | Estado | Notas |
|---|-----------|--------|------|------|--------|-------|
| 1 | lml_users_mesa4core | lml_users | truth_source | ~7,891 | ✅ Completo | Fuente de verdad para usuarios |
| 2 | lml_usersgroups_mesa4core | lml_usersgroups | truth_source* | ~N | ✅ Completo | Depende de lml_users |
| 3 | lml_processes_mesa4core | lml_processes | consumer | ~129,000 | ✅ Completo | Timestamps validados |
| 4 | lml_listbuilder_mesa4core | lml_listbuilder | consumer | ~200 | ✅ Completo | Configs de UI |
| 5 | lml_formbuilder_mesa4core | lml_formbuilder | consumer | ~N | ✅ Completo | Formularios dinámicos |
| 6 | lml_processtypes_mesa4core | lml_processtypes | consumer | ~N | ✅ Completo | Tipos de trámites |
| 7 | lml_people_mesa4core | lml_people | consumer | ~23,085 | ✅ Completo | Personas físicas/jurídicas |
| 8 | [Pendiente] | - | - | - | 🔧 Pendiente | - |

**Nota**: `*` = truth_source con dependencia (caso especial)

### Hitos Técnicos Logrados

- ✅ Arquitectura multi-colección con carga dinámica
- ✅ Suite de tests automatizada (sintaxis, config, interfaz, schemas)
- ✅ Tests dinámicos (se autoactualiz an con nuevas colecciones)
- ✅ Patrón estandarizado para `_parse_timestamp` (maneja datetime nativo de pymongo)
- ✅ Sistema de Ghost Users para auditoría
- ✅ Validación de dependencias pre-migración
- ✅ Manejo robusto de timestamps (Extended JSON, ISO8601, datetime objects)

---

## Arquitectura Técnica

### Topología de Datos

```
                    ┌─────────────────────────────────┐
                    │      MongoDB (mesa4core)        │
                    │    ~8 colecciones anidadas      │
                    └────────────┬────────────────────┘
                                 │
                         Transformación
                         (mongomigra.py)
                                 │
                    ┌────────────▼────────────────────┐
                    │   PostgreSQL (mesamongo)        │
                    │                                 │
                    │  ┌─────────────────────────┐   │
                    │  │  Schema: lml_users      │   │
                    │  │  (Truth Source)         │   │
                    │  │  - main                 │   │
                    │  │  - roles, areas, etc    │   │
                    │  └─────────────────────────┘   │
                    │             ▲                   │
                    │             │ FK                │
                    │  ┌──────────┴──────────────┐   │
                    │  │ Schemas específicos:    │   │
                    │  │ - lml_processes         │   │
                    │  │ - lml_listbuilder       │   │
                    │  │ - lml_formbuilder       │   │
                    │  │ - lml_processtypes      │   │
                    │  │ - lml_people            │   │
                    │  │ - lml_usersgroups       │   │
                    │  └─────────────────────────┘   │
                    └─────────────────────────────────┘
```

### Patrón de Schema

**Schema por colección**: Cada colección MongoDB → 1 schema PostgreSQL

**Ventajas**:
- ✅ Sin colisiones de nombres (cada schema tiene su propia `main`)
- ✅ Organización clara (propiedad de datos evidente)
- ✅ FKs simples (`REFERENCES lml_users.main`)
- ✅ Escalable (agregar colección = nuevo schema aislado)

### Tipos de Migradores

**1. truth_source**
- No dependen de otros schemas
- Son la fuente de verdad para sus datos
- Ejemplo: `lml_users`

**2. consumer**
- Dependen de otros schemas vía FKs
- Deben migrarse después de sus dependencias
- Ejemplo: `lml_processes` (depende de `lml_users`)

**3. truth_source con dependencia** (caso especial)
- Es truth_source para sus datos propios
- Pero depende de otro schema para FKs
- Ejemplo: `lml_usersgroups` (depende de `lml_users` para members.user_id)

---

## Decisiones Técnicas

### 1. Full Refresh con TRUNCATE CASCADE

**Decisión**: Full refresh en cada migración

**Implementación actual**:
```python
# mongomigra.py - PASO 3: FULL REFRESH
pg_cursor.execute(
    f"TRUNCATE TABLE {schema}.main CASCADE"
)
```

**Justificación**:
- MongoDB es sistema legacy (datos históricos no cambian mucho)
- Garantiza consistencia total con origen
- Idempotente: se puede re-ejecutar sin problemas
- Más simple que sincronización incremental

**Para producción** (sincronización nocturna):
- Crear script `reset_database.py` que elimine TODOS los schemas
- Ejecutar: reset → dbsetup → mongomigra (todas las colecciones)
- Automatizar con cron/scheduler

### 2. Manejo de Timestamps

**Problema**: MongoDB almacena fechas en múltiples formatos

**Solución estandarizada** (método `_parse_timestamp`):

```python
def _parse_timestamp(self, value):
    """Parsea timestamps de MongoDB a datetime de Python."""
    if not value:
        return None
    
    try:
        # Caso 1: datetime nativo (pymongo lo convierte automáticamente)
        if isinstance(value, datetime):
            return value
        
        # Caso 2: Extended JSON
        if isinstance(value, dict) and '$date' in value:
            value = value['$date']
        
        # Caso 3: String ISO8601
        if isinstance(value, str):
            if value.endswith('Z'):
                if '.' in value:
                    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
                else:
                    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            
            if '+' in value or value.count('-') > 2:
                return datetime.fromisoformat(value)
    
    except (ValueError, TypeError):
        return None
    
    return None
```

**CRÍTICO**: Todos los migradores DEBEN tener este método y usar `from datetime import datetime`

**Fallback opcional** (para datos con nulls):
```python
now = datetime.now(timezone.utc)
created_at = self._parse_timestamp(doc.get('createdAt')) or now
updated_at = self._parse_timestamp(doc.get('updatedAt')) or created_at
```

### 3. Ghost Users para Auditoría

**Problema**: Snapshots de auditoría (createdBy/updatedBy) referencian usuarios que pueden no existir en lml_users

**Solución**: Sistema de Ghost Users

1. **Detección**: Al procesar documento, verificar si usuario existe en caché
2. **Extracción**: Si no existe, extraer datos del snapshot
3. **Cola**: Acumular en `self.ghost_users_queue`
4. **Inserción masiva**: Antes de insertar datos principales, insertar ghost users con `deleted=TRUE`

**Ventajas**:
- ✅ Mantiene integridad referencial (FKs no fallan)
- ✅ Preserva información histórica
- ✅ Performance: bulk insert en vez de uno por uno

### 4. Normalización vs JSONB

**Matriz de decisión**:

| Criterio | → Tabla | → JSONB |
|----------|---------|---------|
| ¿Se consulta en WHERE? | ✅ | 🚫 |
| ¿Tiene FK? | ✅ | 🚫 |
| ¿Estructura fija? | ✅ | 🚫 |
| ¿1:N con muchos registros? | ✅ | 🚫 |
| ¿Estructura variable? | 🚫 | ✅ |
| ¿Solo se muestra completo? | 🚫 | ✅ |
| ¿Metadata técnica? | 🚫 | ✅ |

**Regla de oro**: "SIEMPRE que se pueda campos individuales con información relevante, van individuales. El objetivo es lograr que sea relacional."

---

## Estructura de Código

### Árbol de Directorios

```
mongo_to_postgre/
├── .env                      # Credenciales (NO committear)
├── .gitignore
├── requirements.txt
├── README.md
├── context.md               # Este documento
│
├── config.py                # Configuración centralizada
├── dbsetup.py               # Setup de schemas/tablas (ejecutar antes de migrar)
├── mongomigra.py            # Motor principal de migración
│
├── migrators/               # Migradores por colección
│   ├── __init__.py
│   ├── base.py              # BaseMigrator (interfaz abstracta)
│   ├── lml_users.py
│   ├── lml_usersgroups.py
│   ├── lml_processes.py
│   ├── lml_listbuilder.py
│   ├── lml_formbuilder.py
│   ├── lml_processtypes.py
│   └── lml_people.py
│
├── tests/                   # Suite de tests automatizada
│   ├── run_tests.py         # Runner principal
│   ├── helpers.py           # Funciones helper dinámicas
│   ├── test_syntax.py       # Validación de sintaxis Python
│   ├── test_config.py       # Validación de config.py
│   ├── test_migrator_interface.py  # Validación de interfaz BaseMigrator
│   └── test_schema_integrity.py    # Validación de coherencia schemas
│
├── skills/                  # Skills para document creation (opcional)
│   └── ...
│
└── samples/                 # Muestras para análisis
    └── ...
```

### Archivos Clave

**config.py**:
- `COLLECTIONS`: Dict con configuración de cada colección
- `MIGRATION_ORDER`: Lista ordenada respetando dependencias
- Funciones helper: `get_collection_config()`, `validate_migration_order()`, etc

**dbsetup.py**:
- Funciones `setup_<schema>_schema(cursor)` para cada colección
- Patrón: Solo cursor (no conn), sin prints intermedios, un commit final en main()
- Índices agrupados en un solo `execute()`

**mongomigra.py**:
- Orquestador agnóstico de lógica de negocio
- Carga dinámica de migradores con `importlib`
- Validación de dependencias pre-migración
- Batch processing con BATCH_SIZE=2000

**migrators/base.py**:
- Clase abstracta `BaseMigrator`
- Define interfaz requerida:
  - `extract_shared_entities(doc, cursor, caches)`
  - `extract_data(doc, shared_entities)`
  - `insert_batches(batches, cursor, caches)`
  - `initialize_batches()`
  - `get_primary_key_from_doc(doc)`

---

## Convenciones y Patrones

### Nomenclatura

**Campos**:
- MongoDB: camelCase (`processId`, `createdAt`)
- PostgreSQL: snake_case (`process_id`, `created_at`)
- Semántica de negocio: `process_id` (no `mongo_id`)

**Clases**:
- PascalCase con sufijo: `LmlPeopleMigrator`

**Métodos**:
- Públicos: `snake_case` (`extract_data`)
- Privados: `_snake_case` (`_parse_timestamp`)

**Schemas/Tablas**:
- Schema: `lml_<collection_name>` (ej: `lml_people`)
- Tabla principal: `main`
- Tablas relacionadas: `snake_case` descriptivo

### Patrón de Migrador

**Estructura típica**:

```python
class LmlXxxMigrator(BaseMigrator):
    def __init__(self, schema='lml_xxx'):
        super().__init__(schema)
        self.ghost_users_queue = []  # Si es consumer
    
    # Métodos públicos (interfaz)
    def extract_shared_entities(self, doc, cursor, caches):
        """Procesa usuarios, carga cachés, etc."""
        pass
    
    def extract_data(self, doc, shared_entities):
        """Extrae datos estructurados del documento."""
        return {
            'main': self._extract_main_record(doc, shared_entities),
            'related': {
                'table1': self._extract_table1(doc, pk),
                'table2': self._extract_table2(doc, pk),
            }
        }
    
    def insert_batches(self, batches, cursor, caches):
        """Inserta ghost users, luego main, luego related."""
        # 1. Ghost users (si hay)
        if self.ghost_users_queue:
            # Bulk insert con execute_values
            self.ghost_users_queue = []
        
        # 2. Main table
        if batches['main']:
            self._insert_main_batch(batches['main'], cursor)
        
        # 3. Related tables
        for table_name, records in batches['related'].items():
            if records:
                method = getattr(self, f'_insert_{table_name}_batch')
                method(records, cursor)
    
    # Métodos privados (helpers)
    def _parse_timestamp(self, value):
        """Parsea timestamps (método estándar)."""
        pass
    
    def _extract_main_record(self, doc, shared_entities):
        """Extrae tupla para tabla main."""
        pass
    
    def _insert_main_batch(self, batch, cursor):
        """Inserta batch en tabla main con execute_values."""
        pass
```

### Patterns de INSERT

**Para catálogos** (pueden actualizarse):
```sql
INSERT INTO schema.table (id, name) VALUES %s
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
```

**Para datos principales** (preservar primer insert):
```sql
INSERT INTO schema.main (...) VALUES %s
ON CONFLICT (id) DO NOTHING
```

**Para tablas de relación N:M con sincronización** (ej: usersgroups.members):
```python
# DELETE viejos + INSERT nuevos (por grupo)
for group_id, members in groups_members.items():
    cursor.execute(f"DELETE FROM {schema}.members WHERE group_id = %s", (group_id,))
    if members:
        execute_values(cursor, f"INSERT INTO {schema}.members (...) VALUES %s", members)
```

---

## Testing

### Suite de Tests

**Ejecutar todos**:
```bash
python tests/run_tests.py
```

**Tests individuales**:
1. **test_syntax.py**: Valida sintaxis Python (compila sin ejecutar)
2. **test_config.py**: Valida `COLLECTIONS`, `MIGRATION_ORDER`, dependencias
3. **test_migrator_interface.py**: Valida que migradores implementan interfaz BaseMigrator
4. **test_schema_integrity.py**: Valida que métodos `_insert_*_batch` existan para cada tabla

### Tests Dinámicos

**Características**:
- Se autoactualualizan al agregar colecciones
- Leen de `config.MIGRATION_ORDER` dinámicamente
- Cargan migradores con `importlib` (sin imports hardcodeados)

**Archivo helper**: `tests/helpers.py`
- `get_all_migrator_classes()`: Carga clases dinámicamente
- `get_all_migrator_instances()`: Instancia migradores
- `get_migrator_class_for_collection(name)`: Carga migrador específico

**Excepciones conocidas**: `test_schema_integrity.py` tiene dict de excepciones para métodos con nombres alternativos (ej: `_sync_members_batch` en vez de `_insert_members_batch`)

---

## Workflow de Migración

### Agregar Nueva Colección (Paso a Paso)

**1. Análisis (descubrimiento)**:
```bash
# Exportar muestra
python export_sample.py lml_nueva_coleccion_mesa4core 200

# Crear analyzer personalizado (copiar de otro)
# Ejecutar y analizar resultados
python analyze_nueva_coleccion.py
```

**2. Configuración**:

Actualizar `config.py`:
```python
"lml_nueva_coleccion_mesa4core": {
    "postgres_schema": "lml_nueva",
    "primary_key": "nueva_id",
    "collection_type": "consumer",  # o "truth_source"
    "depends_on": ["lml_users_mesa4core"],  # si aplica
    "description": "Descripción de la colección",
}
```

Agregar a `MIGRATION_ORDER` respetando dependencias.

**3. Schema (dbsetup.py)**:

Crear función `setup_lml_nueva_schema(cursor)`:
```python
def setup_lml_nueva_schema(cursor):
    """
    Crea schema lml_nueva con estructura completa.
    
    TABLAS:
    - main: Datos principales
    - related_table: Tabla relacionada
    """
    print("\n   🔧 Creando schema 'lml_nueva'...")
    
    cursor.execute("CREATE SCHEMA IF NOT EXISTS lml_nueva")
    
    # Tabla main
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_nueva.main (
            nueva_id VARCHAR(255) PRIMARY KEY,
            campo1 VARCHAR(255),
            campo2 TIMESTAMP,
            created_by_user_id VARCHAR(255) REFERENCES lml_users.main(id),
            ...
        )
    """)
    
    # Índices (agrupados en un execute)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_nueva_campo1 ON lml_nueva.main(campo1);
        CREATE INDEX IF NOT EXISTS idx_nueva_created_by ON lml_nueva.main(created_by_user_id);
    """)
    
    print("   ✅ Schema 'lml_nueva' creado (N tablas + M índices)")
```

Agregar llamada en `main()`.

**4. Migrador (migrators/lml_nueva.py)**:

Copiar estructura de migrador similar y adaptar. Asegurarse de:
- ✅ Heredar de `BaseMigrator`
- ✅ Implementar todos los métodos abstractos
- ✅ Incluir `from datetime import datetime`
- ✅ Incluir método `_parse_timestamp` estándar
- ✅ Manejar Ghost Users si es consumer
- ✅ Usar `execute_values` para bulk insert

**5. Tests**:
```bash
# Ejecutar suite completa
python tests/run_tests.py

# Si todos pasan:
python dbsetup.py          # Crea schema/tablas
python mongomigra.py       # Ejecuta migración
```

**6. Validación**:
```sql
-- Verificar conteos
SELECT COUNT(*) FROM lml_nueva.main;

-- Verificar timestamps
SELECT 
    MIN(created_at) as mas_antiguo,
    MAX(created_at) as mas_reciente,
    COUNT(CASE WHEN created_at > NOW() - INTERVAL '1 hour' THEN 1 END) as ultima_hora
FROM lml_nueva.main;

-- Verificar FKs
SELECT COUNT(*) 
FROM lml_nueva.main m
LEFT JOIN lml_users.main u ON m.created_by_user_id = u.id
WHERE m.created_by_user_id IS NOT NULL AND u.id IS NULL;
-- Debería dar 0
```

---

## Troubleshooting

### Error: "null value in column 'created_at' violates not-null constraint"

**Causa**: Timestamps null en MongoDB o `_parse_timestamp` retornando None

**Solución**:
```python
# En _extract_main_record, agregar fallback:
now = datetime.now(timezone.utc)
created_at = self._parse_timestamp(doc.get('createdAt')) or now
updated_at = self._parse_timestamp(doc.get('updatedAt')) or created_at
```

### Error: "datetime not defined"

**Causa**: Falta import de datetime

**Solución**:
```python
from datetime import datetime  # ← Agregar al inicio del migrador
```

### Timestamps con fechas de "hoy" en vez de 2022

**Causa**: `_parse_timestamp` no maneja `datetime` objects (pymongo los convierte automáticamente)

**Solución**: Verificar que método empiece con:
```python
if isinstance(value, datetime):
    return value
```

### Error: "LmlXxxMigrator: Falta método _insert_table_batch()"

**Causa 1**: Falta definir el método
**Causa 2**: El método tiene nombre alternativo (ej: `_sync_members_batch`)

**Solución para Causa 2**: Agregar excepción en `tests/test_schema_integrity.py`:
```python
EXCEPTIONS = {
    'LmlXxxMigrator': {
        'table_name': '_alternative_method_name'
    }
}
```

### Migración muy lenta

**Diagnóstico**:
- ¿BATCH_SIZE muy pequeño? Aumentar a 2000-5000
- ¿Commits demasiado frecuentes? Hacer commit cada batch, no cada insert
- ¿Validaciones en loop? Usar caché (ej: `valid_user_ids` en set)

**Optimizaciones**:
- Usar `execute_values` en vez de `executemany`
- Agrupar índices en un solo `execute()`
- Verificar que caché de usuarios se carga solo una vez

---

## Mejoras Futuras

### Corto Plazo

1. **Script reset_database.py**
   - Eliminar TODOS los schemas antes de migración nocturna
   - Confirmar con `input("SI")` para seguridad
   - Leer schemas de `config.py` dinámicamente

2. **Estandarizar lml_processes.py**
   - Agregar método `_parse_timestamp` (aunque funcione sin él)
   - Mantener consistencia con otros migradores

3. **Validación post-migración automatizada**
   - Script que valida conteos, FKs, timestamps
   - Integrar en `mongomigra.py` al final de cada migración

### Mediano Plazo

1. **Modo batch no-interactivo**
   - Flag `--all` para migrar todas las colecciones en orden
   - Logging a archivo en vez de consola
   - Para automatización con cron

2. **Migración paralela**
   - Migrar colecciones independientes en paralelo
   - Requiere análisis de dependencias en grafo

3. **Métricas y monitoring**
   - Tiempo por colección
   - Memoria utilizada
   - Docs/segundo
   - Alertas si migración falla

### Largo Plazo

1. **Sincronización incremental**
   - Para colecciones que cambian frecuentemente
   - Requiere tracking de `updatedAt` confiable
   - Lógica de merge/upsert compleja

2. **Rollback automatizado**
   - Snapshot de PostgreSQL antes de migración
   - Rollback si validaciones fallan

---

## Historial de Versiones

| Versión | Fecha | Cambios Principales |
|---------|-------|---------------------|
| v1.0 | 2025-10-30 | POC inicial: migración monolítica de lml_processes |
| v2.0 | 2025-11-05 | Refactorización: nomenclatura semántica |
| v3.0 | 2025-11-15 | Arquitectura multi-colección: BaseMigrator + carga dinámica |
| v3.1 | 2025-11-19 | Segunda colección (lml_listbuilder) + documentación |
| v4.0 | 2025-12-17 | 7 colecciones migradas, tests dinámicos, `_parse_timestamp` estandarizado |

---

## Recursos Adicionales

**Documentación PostgreSQL**:
- Foreign Keys: https://www.postgresql.org/docs/current/ddl-constraints.html
- JSONB: https://www.postgresql.org/docs/current/datatype-json.html
- Batch INSERT: https://www.psycopg.org/docs/extras.html

**Documentación MongoDB**:
- Extended JSON: https://www.mongodb.com/docs/manual/reference/mongodb-extended-json/
- PyMongo: https://pymongo.readthedocs.io/

**Herramientas**:
- DBeaver: Cliente SQL multi-plataforma
- MongoDB Compass: GUI para MongoDB
- pgAdmin: Cliente oficial de PostgreSQL

---

**Última actualización**: 2025-12-17  
**Versión**: v4.0 (7/~8 colecciones migradas)  
**Estado**: Sistema estable, listo para automatización nocturna
