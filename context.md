# Context: Sistema de Migración MongoDB → PostgreSQL

**Última actualización:** 2025-01-19  
**Estado del proyecto:** En desarrollo activo (2/8 colecciones migradas)  
**Propósito de este documento:** Continuidad técnica y de metodología de trabajo

---

## 📖 Tabla de Contenidos

1. [Cómo Usar Este Documento](#cómo-usar-este-documento)
2. [Filosofía de Trabajo](#filosofía-de-trabajo)
   - [Estilo de Comunicación](#estilo-de-comunicación)
   - [Metodología de Resolución](#metodología-de-resolución)
   - [Estilo de Código](#estilo-de-código)
3. [Estado Actual del Proyecto](#estado-actual-del-proyecto)
4. [Arquitectura Técnica](#arquitectura-técnica)
   - [Topología de Datos](#topología-de-datos)
   - [Patrón de Schema](#patrón-de-schema)
   - [Flujo de Migración](#flujo-de-migración)
5. [Decisiones Técnicas](#decisiones-técnicas)
6. [Estructura de Código](#estructura-de-código)
7. [Convenciones](#convenciones)
8. [Workflow de Análisis](#workflow-de-análisis)
9. [Agregar Nueva Colección](#agregar-nueva-colección)
10. [Testing](#testing)
11. [Configuración de Performance](#configuración-de-performance)
12. [Troubleshooting](#troubleshooting)
13. [Métricas y Recursos](#métricas-y-recursos)

---

## Cómo Usar Este Documento

Este documento es la **memoria técnica del proyecto**. Su propósito es triple:

1. **Para Asistentes IA**: Entender el contexto completo sin necesidad de explorar todo el código
2. **Para Desarrolladores**: Referencia rápida de decisiones, patrones y convenciones
3. **Para Continuidad**: Permitir que cualquier persona retome el trabajo sin perder el hilo

### Estructura de Lectura Recomendada

- **Primera vez**: Lee completo de inicio a fin (30-40 minutos)
- **Agregar colección nueva**: Secciones 8, 9, 6, 10 (en ese orden)
- **Debugging**: Sección 12 (Troubleshooting) primero, luego contexto específico
- **Optimización**: Secciones 11, 13

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
- Anticipar preguntas del lector

**Ejemplo de buena explicación**:
```
❌ Mal: "Usamos BATCH_SIZE = 2000"
✅ Bien: "BATCH_SIZE = 2000 balancea memoria vs velocidad. 
         Mayor = más rápido pero riesgo de OOM.
         Menor = más lento pero más seguro.
         2000 procesa ~129k docs en 20min sin problemas."
```

### Metodología de Resolución

**Flujo estándar para agregar una colección**:

1. **Análisis** (30-40% del tiempo)
   - Exportar sample: `python export_sample.py <collection> 200`
   - Análisis manual del JSON exportado
   - Identificar patrones de normalización
   - Decidir qué va a tablas vs JSONB

2. **Diseño** (20-30% del tiempo)
   - Diseñar schema PostgreSQL
   - Definir claves primarias y foráneas
   - Mapear campos MongoDB → PostgreSQL

3. **Implementación** (30-40% del tiempo)
   - Crear tablas en `dbsetup.py`
   - Implementar migrador heredando de `BaseMigrator`
   - Testing iterativo con subconjuntos

4. **Validación** (10% del tiempo)
   - Verificar conteos: MongoDB vs PostgreSQL
   - Verificar integridad referencial
   - Probar queries representativas

### Estilo de Código

**Principios fundamentales**:

1. **Explícito > Implícito**
   ```python
   # ❌ Mal
   def process(d):
       return d.get('id')
   
   # ✅ Bien
   def extract_user_id_from_document(document: dict) -> str:
       """Extrae user_id desde documento MongoDB."""
       return document.get('id')
   ```

2. **Docstrings completos**
   - Qué hace la función
   - Parámetros con tipos y significado
   - Retorno con estructura esperada
   - Ejemplo de uso si no es obvio

3. **Nombres semánticos**
   ```python
   # ❌ Mal: nombres técnicos
   mongo_id, record_id
   
   # ✅ Bien: nombres de negocio
   process_id, listbuilder_id
   ```

4. **Separación de responsabilidades**
   - Métodos públicos: Interfaz (qué hace)
   - Métodos privados: Implementación (cómo lo hace)
   - Un método = una responsabilidad clara

---

## Estado Actual del Proyecto

### Visión General
Sistema de migración desde MongoDB (`mesa4core`) a PostgreSQL (`mesamongo`). Objetivo: transformar documentos NoSQL anidados en modelo relacional normalizado.

### Razones de la Migración

1. **Integridad de Datos**: Implementar integridad referencial mediante claves foráneas y restricciones
2. **Normalización**: Eliminar la duplicación de datos inherente al modelo desnormalizado de MongoDB
3. **Consultas Complejas**: Habilitar JOINs eficientes y consultas relacionales complejas
4. **Estandarización**: Consolidar entidades compartidas (usuarios, áreas, clientes) en tablas de única fuente de verdad

### Colecciones Migradas

| Colección | Schema | Documentos | Estado | Tiempo | Docs/seg |
|-----------|--------|------------|--------|--------|----------|
| ✅ lml_processes_mesa4core | lml_processes | ~129,000 | Completo | ~20 min | ~107 |
| ✅ lml_listbuilder_mesa4core | lml_listbuilder | ~200 | Completo | <1 min | N/A |
| 🔧 [Pendiente] | - | - | - | - | - |

### Próximos Pasos Inmediatos

1. ✅ Separar setup de migración (dbsetup.py ≠ mongomigra.py)
2. ✅ Sistema de carga dinámica de migradores
3. 🔧 Migrar siguiente colección (TBD)
4. 🔧 Implementar tests de integridad

---

## Arquitectura Técnica

### Topología de Datos

```
                    ┌─────────────────────────────────┐
                    │      MongoDB (mesa4core)        │
                    │    ~N colecciones anidadas      │
                    └────────────┬────────────────────┘
                                 │
                         Transformación
                         (mongomigra.py)
                                 │
                    ┌────────────▼────────────────────┐
                    │   PostgreSQL (mesamongo)        │
                    │                                 │
                    │  ┌─────────────────────────┐   │
                    │  │   Schema: public        │   │
                    │  │   (Entidades Comunes)   │   │
                    │  │   - users               │   │
                    │  │   - customers           │   │
                    │  │   - areas/subareas      │   │
                    │  │   - roles/groups        │   │
                    │  └─────────────────────────┘   │
                    │                                 │
                    │  ┌─────────────────────────┐   │
                    │  │  Schema: lml_processes  │   │
                    │  │  (Datos Específicos)    │   │
                    │  │  - main                 │   │
                    │  │  - movements            │   │
                    │  │  - documents            │   │
                    │  └─────────────────────────┘   │
                    │                                 │
                    │  ┌─────────────────────────┐   │
                    │  │ Schema: lml_listbuilder │   │
                    │  │  (Configs UI)           │   │
                    │  │  - main                 │   │
                    │  │  - fields               │   │
                    │  │  - items                │   │
                    │  └─────────────────────────┘   │
                    └─────────────────────────────────┘
```

### Patrón de Schema

**Arquitectura Híbrida**: Separación entre entidades compartidas y específicas.

#### Schema Public (Entidades Compartidas)
Aloja entidades que se reutilizan a través de múltiples colecciones:

```sql
-- Tabla de usuarios (referenciada por TODAS las colecciones)
CREATE TABLE public.users (
    id VARCHAR(255) PRIMARY KEY,
    email VARCHAR(255),  -- Sin UNIQUE (ver Decisiones Técnicas)
    firstname VARCHAR(255),
    lastname VARCHAR(255),
    area_id VARCHAR(255) REFERENCES public.areas(id),
    subarea_id VARCHAR(255) REFERENCES public.subareas(id),
    role_id VARCHAR(255) REFERENCES public.roles(id)
);

-- Clientes (entidad de negocio central)
CREATE TABLE public.customers (
    id VARCHAR(255) PRIMARY KEY
);

-- Jerarquía organizacional
CREATE TABLE public.areas (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255)
);

CREATE TABLE public.subareas (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255)
);
```

#### Schemas Específicos por Colección
Cada colección MongoDB obtiene su propio schema:

```sql
-- Schema para lml_processes
CREATE SCHEMA IF NOT EXISTS lml_processes;

CREATE TABLE lml_processes.main (
    process_id VARCHAR(255) PRIMARY KEY,  -- Semantic naming!
    process_number VARCHAR(255),
    customer_id VARCHAR(255) REFERENCES public.customers(id),
    created_by_user_id VARCHAR(255) REFERENCES public.users(id),
    -- ... más columnas
);

CREATE TABLE lml_processes.movements (
    id SERIAL PRIMARY KEY,
    process_id VARCHAR(255) REFERENCES lml_processes.main(process_id),
    movement_at TIMESTAMP,
    -- ... más columnas
);
```

### Flujo de Migración

```
┌────────────────────────────────────────────────────────────────┐
│                        FLUJO COMPLETO                          │
└────────────────────────────────────────────────────────────────┘

1. SETUP (Una sola vez)
   ↓
   python dbsetup.py
   ↓
   Crea todos los schemas y tablas

2. MIGRACIÓN (Por colección)
   ↓
   python mongomigra.py
   ↓
   Seleccionar colección del menú
   ↓
   ┌──────────────────────────────────────────────┐
   │  Iteración sobre documentos (batches)       │
   │                                              │
   │  Por cada documento:                         │
   │  1. extract_shared_entities()                │
   │     → Inserta/actualiza public.*            │
   │     → Usa caché para evitar duplicados      │
   │                                              │
   │  2. extract_data()                           │
   │     → Extrae datos específicos              │
   │     → Retorna estructura normalizada        │
   │                                              │
   │  3. Acumular en batches                      │
   │                                              │
   │  Cada BATCH_SIZE documentos:                 │
   │  4. insert_batches()                         │
   │     → executemany() para bulk insert        │
   │     → commit a PostgreSQL                   │
   └──────────────────────────────────────────────┘
   ↓
   Migración completa
```

### ¿Por qué Híbrido vs. Schema Único?

| Criterio | Híbrido (✅ Elegido) | Schema Único (🚫 Descartado) |
|----------|---------------------|---------------------------|
| Organización | Clara separación compartido/específico | Todo mezclado |
| Escalabilidad | Sin colisiones de nombres | Risk de colisión: lml_processes.main vs lml_listbuilder.main |
| Mantenibilidad | Fácil entender propiedad de datos | Difícil saber qué tabla usa qué colección |
| Foreign Keys | Simples: `REFERENCES public.users` | Complejas: referencias cruzadas |
| Futuro | Agregar colección = nuevo schema | Agregar colección = posibles conflictos |

---

## Decisiones Técnicas

### 1. Full Refresh vs Incremental Sync

**Decisión**: Full Refresh (recrear datos cada vez)

**Justificación**:
- MongoDB es sistema legacy, datos históricos no cambian
- Sincronización incremental requiere:
  - Tracking de `updatedAt` (no confiable en origen)
  - Lógica de merge/upsert compleja
  - Riesgo de inconsistencias
- Full refresh garantiza consistencia total

**Trade-offs**:
```
Full Refresh:
  ✅ Siempre consistente con origen
  ✅ Lógica simple (solo INSERTs)
  ✅ Idempotente (re-ejecutable)
  🚫 Tiempo de downtime en cada migración

Incremental:
  ✅ Rápido para updates pequeños
  🚫 Complejidad alta
  🚫 Requiere auditoría de cambios
  🚫 Riesgo de drift entre sistemas
```

**Implementación**:
```python
# Idempotencia via ON CONFLICT
INSERT INTO public.users (id, email, ...) 
VALUES (%s, %s, ...) 
ON CONFLICT (id) DO NOTHING;
```

### 2. Eliminación de UNIQUE(email) en public.users

**Decisión**: `email` sin constraint UNIQUE

**Razones**:
1. **Datos sucios en origen**: MongoDB tiene usuarios con emails duplicados
2. **Historia de cambios**: Mismo usuario puede tener múltiples emails a lo largo del tiempo
3. **IDs son PK real**: `user.id` es el identificador único verdadero

**Ejemplo del problema**:
```
Usuario A: {id: "USR001", email: "juan@ejemplo.com"}
Usuario B: {id: "USR002", email: "juan@ejemplo.com"}  # Mismo email!

Con UNIQUE(email) → Error de constraint
Sin UNIQUE(email) → Ambos se insertan correctamente
```

**Consecuencias**:
- ✅ Migración no falla por duplicados
- ⚠️ Queries por email pueden retornar múltiples usuarios
- 💡 Siempre usar `user.id` como referencia, no email

### 3. Estrategia de ON CONFLICT

**Decisión**: Usar `ON CONFLICT` pero diferenciado por tipo de tabla

**Para tablas compartidas (public.*)**:
```sql
-- Opción A: DO NOTHING (elegida)
INSERT INTO public.users (...) VALUES (...)
ON CONFLICT (id) DO NOTHING;

-- ¿Por qué NO DO UPDATE?
-- Porque el primer documento que procesamos puede no tener
-- los datos más actualizados. DO NOTHING asegura que el
-- primer insert completo se preserva.
```

**Para tablas específicas con PK natural**:
```sql
-- También DO NOTHING
INSERT INTO lml_processes.main (process_id, ...) VALUES (...)
ON CONFLICT (process_id) DO NOTHING;
```

**Para tablas relacionadas sin constraint único**:
```sql
-- Sin ON CONFLICT (pueden haber duplicados legítimos)
INSERT INTO lml_processes.movements (process_id, movement_at, ...) 
VALUES (...);
```

### 4. Normalización vs JSON

**Decisión**: Matriz de decisión basada en criterios

| Criterio | → Tabla Normalizada | → Campo JSONB |
|----------|---------------------|---------------|
| ¿Se consulta en WHERE? | ✅ | 🚫 |
| ¿Tiene FK a public.*? | ✅ | 🚫 |
| ¿Estructura fija? | ✅ | 🚫 |
| ¿1:N con muchos registros? | ✅ | 🚫 |
| ¿Estructura variable? | 🚫 | ✅ |
| ¿Solo se muestra completo? | 🚫 | ✅ |
| ¿Metadata técnica? | 🚫 | ✅ |
| ¿1:N con pocos items (<10)? | 🚫 | ✅ |

**Ejemplos del proyecto**:

```python
# ✅ Tabla normalizada: movements
# Razón: 1:N con muchos registros, se consultan, tienen timestamps
CREATE TABLE lml_processes.movements (
    id SERIAL PRIMARY KEY,
    process_id VARCHAR(255) REFERENCES lml_processes.main,
    movement_at TIMESTAMP,
    destination_id VARCHAR(255)
);

# ✅ JSONB: gqlVariables en listbuilder
# Razón: Estructura variable, metadata técnica, solo se usa completo
CREATE TABLE lml_listbuilder.main (
    listbuilder_id VARCHAR(255) PRIMARY KEY,
    gql_variables JSONB,  -- Variable structure
    ...
);

# 🚫 Anti-patrón: NO hacer esto
CREATE TABLE bad_example (
    id VARCHAR(255) PRIMARY KEY,
    user_data JSONB  -- ❌ Usuario debería ser FK a public.users
);
```

---

## Estructura de Código

### Árbol de Directorios

```
mongo_to_postgre/
├── .env                      # Credenciales (NO committear)
├── .gitignore
├── requirements.txt          # Dependencies: pymongo, psycopg2, python-dotenv
├── README.md
├── context.md               # Este documento
│
├── config.py                # ⭐ Configuración centralizada
│   ├── MONGO_URI
│   ├── POSTGRES_CONFIG
│   ├── TABLE_NAMES
│   ├── BATCH_SIZE
│   └── COLLECTIONS          # Mapeo colecciones → schemas
│
├── dbsetup.py               # ⭐ Setup inicial (ejecutar UNA VEZ)
│   └── Crea schemas y tablas en PostgreSQL
│
├── mongomigra.py            # ⭐ Motor principal de migración
│   ├── connect_to_mongo()
│   ├── connect_to_postgres()
│   ├── load_migrator_for_collection()  # Dynamic loading
│   ├── show_collection_menu()
│   └── migrate_collection()            # Main loop
│
├── migrators/               # ⭐ Migradores específicos por colección
│   ├── __init__.py
│   ├── base.py              # BaseMigrator (interfaz abstracta)
│   ├── lml_processes.py     # LmlProcessesMigrator
│   └── lml_listbuilder.py   # LmlListbuilderMigrator
│
├── export_sample.py         # 🔧 Herramienta: exportar JSON de colección
├── analyze_listbuilder.py   # 🔧 Herramienta: analizar estructura
│
├── samples/                 # Muestras exportadas (para análisis)
│   ├── lml_processes_mesa4core_sample.json
│   └── lml_listbuilder_mesa4core_sample.json
│
└── v1 lml_processes/        # Versión legacy (referencia histórica)
    ├── mongomigra.py        # Versión monolítica original
    └── config.py
```

### Herramientas de Análisis

#### export_sample.py

**Propósito**: Exportar muestra de colección para análisis manual.

**Uso**:
```bash
python export_sample.py lml_listbuilder_mesa4core 200
```

**Output**: `samples/lml_listbuilder_mesa4core_sample.json`

**Cuándo usar**:
- Antes de diseñar schema de nueva colección
- Para entender estructura de documentos
- Para identificar patrones de anidamiento

#### analyze_listbuilder.py

**Propósito**: Análisis estadístico de estructura JSON.

**Output ejemplo**:
```
CAMPOS DE PRIMER NIVEL:
  _id                              200/200 (100%)
  alias                            200/200 (100%)
  fields                           198/200 ( 99%)
  customerId                       200/200 (100%)
  
ARRAYS (cardinalidad):
  fields: min=0, max=15, avg=8.5
  items: min=0, max=5, avg=2.1
```

**Cuándo usar**:
- Identificar campos opcionales vs obligatorios
- Decidir normalización de arrays
- Estimar volumetría de tablas relacionadas

### Interfaz BaseMigrator

**Archivo**: `migrators/base.py`

**Patrón de diseño**: Strategy Pattern
- `mongomigra.py` = Context (orquestador)
- `BaseMigrator` = Strategy (interfaz)
- `LmlProcessesMigrator` = Concrete Strategy

**Métodos abstractos obligatorios**:

```python
class BaseMigrator(ABC):
    
    @abstractmethod
    def extract_shared_entities(self, doc, cursor, caches):
        """
        Procesa entidades compartidas (public.*).
        
        Responsabilidades:
        1. Extraer users, customers, areas, etc. del doc
        2. Insertar en public.* con ON CONFLICT DO NOTHING
        3. Usar caches para evitar procesamiento redundante
        4. Retornar IDs para usar en FKs
        
        Returns:
            {'customer_id': str, 'created_by_user_id': str, ...}
        """
    
    @abstractmethod
    def extract_data(self, doc, shared_entities):
        """
        Extrae datos específicos de colección.
        
        Returns:
            {
                'main': tuple,          # Registro principal
                'related': {            # Tablas relacionadas
                    'movements': [tuple, tuple, ...],
                    'documents': [tuple, ...]
                }
            }
        """
    
    @abstractmethod
    def insert_batches(self, batches, cursor):
        """
        Inserta batches acumulados en PostgreSQL.
        
        Debe ejecutar executemany() para cada tipo de registro.
        """
    
    @abstractmethod
    def initialize_batches(self):
        """Retorna estructura vacía para acumular batches."""
    
    @abstractmethod
    def get_primary_key_from_doc(self, doc):
        """Extrae PK value desde documento MongoDB."""
```

### Patrón de Implementación

**Template para agregar nuevo migrador**:

```python
# migrators/mi_coleccion.py

from .base import BaseMigrator
import config

class MiColeccionMigrator(BaseMigrator):
    """
    Migrador para mi_coleccion_mesa4core.
    
    Tablas destino:
    - {schema}.main: ...
    - {schema}.items: ...
    """
    
    def __init__(self, schema='mi_coleccion'):
        super().__init__(schema)
    
    # ===== MÉTODOS PÚBLICOS (INTERFAZ) =====
    
    def extract_shared_entities(self, doc, cursor, caches):
        # 1. Extraer customer_id
        customer_id = doc.get('customerId')
        if customer_id and customer_id not in caches['customers']:
            cursor.execute(
                "INSERT INTO public.customers (id) VALUES (%s) ON CONFLICT DO NOTHING",
                (customer_id,)
            )
            caches['customers'].add(customer_id)
        
        # 2. Extraer usuario creador si existe
        created_by_user_id = None
        if doc.get('createdBy'):
            created_by_user_id = self._process_user(
                doc['createdBy'], cursor, caches
            )
        
        return {
            'customer_id': customer_id,
            'created_by_user_id': created_by_user_id
        }
    
    def extract_data(self, doc, shared_entities):
        pk = self.get_primary_key_from_doc(doc)
        
        return {
            'main': self._extract_main(doc, shared_entities),
            'related': {
                'items': self._extract_items(doc, pk)
            }
        }
    
    def insert_batches(self, batches, cursor):
        if batches['main']:
            cursor.executemany(
                f"INSERT INTO {self.schema}.main (...) VALUES (...)",
                batches['main']
            )
        
        if batches['related']['items']:
            cursor.executemany(
                f"INSERT INTO {self.schema}.items (...) VALUES (...)",
                batches['related']['items']
            )
    
    def initialize_batches(self):
        return {
            'main': [],
            'related': {'items': []}
        }
    
    def get_primary_key_from_doc(self, doc):
        return str(doc['_id'])
    
    # ===== MÉTODOS PRIVADOS (IMPLEMENTACIÓN) =====
    
    def _extract_main(self, doc, shared_entities):
        # Lógica específica...
        pass
    
    def _extract_items(self, doc, pk):
        # Lógica específica...
        pass
```

---

## Convenciones

### Nomenclatura

**Reglas de Mapeo MongoDB → PostgreSQL**:

| Concepto | MongoDB | PostgreSQL | Ejemplo |
|----------|---------|------------|---------|
| Colección | `lml_processes_mesa4core` | Schema: `lml_processes` | `lml_processes.main` |
| Documento `_id` | `ObjectId("...")` | `process_id VARCHAR(255)` | Semantic name! |
| Campo anidado | `createdBy.user.id` | `created_by_user_id` | Snake_case |
| Array pequeño | `items: [...]` | `items JSONB` | Si <10 items |
| Array grande | `movements: [...]` | Tabla `movements` | Si >10 items |
| Timestamp | `ISODate("...")` | `TIMESTAMP` | Ver conversión |

**Clases y Métodos**:
```python
# Clases: PascalCase con sufijo "Migrator"
class LmlProcessesMigrator(BaseMigrator):
    pass

# Métodos públicos: snake_case descriptivo
def extract_shared_entities(self, doc, cursor, caches):
    pass

# Métodos privados: snake_case con prefijo "_"
def _extract_user_data(self, user_obj, cursor, caches):
    pass

# Variables: snake_case
process_id = doc.get('_id')
created_by_user_id = shared['created_by_user_id']
```

### Manejo de Timestamps

**Problema**: MongoDB almacena fechas en múltiples formatos.

**Conversión estandarizada**:

```python
def parse_mongo_timestamp(value):
    """
    Parsea timestamps de MongoDB a datetime de Python.
    
    Formatos soportados:
    1. Extended JSON: {'$date': '2025-01-15T10:30:00.000Z'}
    2. ISO8601 String: '2025-01-15T10:30:00.000Z'
    3. ISO8601 sin ms: '2025-01-15T10:30:00Z'
    4. Epoch millis: 1705318200000
    """
    if not value:
        return None
    
    # Caso 1: Extended JSON
    if isinstance(value, dict) and '$date' in value:
        value = value['$date']
    
    # Caso 2 y 3: String ISO8601
    if isinstance(value, str):
        try:
            if '.' in value:
                return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
            else:
                return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None
    
    # Caso 4: Epoch milliseconds
    if isinstance(value, int):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    
    return None
```

**Uso en migrador**:
```python
def _extract_main_record(self, doc, shared_entities):
    created_at = parse_mongo_timestamp(doc.get('createdAt'))
    updated_at = parse_mongo_timestamp(doc.get('updatedAt'))
    
    return (
        process_id,
        ...,
        created_at,  # Python datetime → PostgreSQL TIMESTAMP
        updated_at
    )
```

### Caching de Entidades Compartidas

**Problema**: Sin caché, cada documento procesa los mismos usuarios repetidamente.

**Impacto medido**:
- Sin caché: ~400 docs/min (5 queries por doc)
- Con caché: ~2,000 docs/min (0.1 queries por doc en promedio)

**Implementación**:

```python
# Inicializar caches antes del loop
caches = {
    'users': set(),
    'customers': set(),
    'areas': set(),
    'subareas': set(),
    'roles': set(),
    'groups': set()
}

# Usar en extract_shared_entities
def extract_shared_entities(self, doc, cursor, caches):
    user_id = doc['createdBy']['user']['id']
    
    # ✅ Check caché primero (O(1) con set)
    if user_id in caches['users']:
        return user_id  # Skip DB operation
    
    # ⚠️ Solo si NO está en caché: INSERT
    cursor.execute(
        "INSERT INTO public.users (...) VALUES (...) ON CONFLICT DO NOTHING",
        (user_id, ...)
    )
    
    # ✅ Agregar a caché para próximas iteraciones
    caches['users'].add(user_id)
    
    return user_id
```

**¿Por qué `set()` y no `list()` o `dict()`?**
- `set()`: O(1) para lookup con `in`
- `list()`: O(n) para lookup (lento con miles de usuarios)
- `dict()`: O(1) pero ocupa más memoria (no necesitamos valores)

---

## Workflow de Análisis

### Proceso Completo de Análisis

```
┌────────────────────────────────────────────────────────────────┐
│               WORKFLOW: AGREGAR NUEVA COLECCIÓN                 │
└────────────────────────────────────────────────────────────────┘

FASE 1: DESCUBRIMIENTO (15-20 min)
  ↓
  ┌─────────────────────────────────────┐
  │ python export_sample.py <col> 200   │  # Exportar muestra
  └─────────────────────────────────────┘
  ↓
  ┌─────────────────────────────────────┐
  │ Abrir samples/<col>_sample.json     │  # Inspección manual
  │                                     │
  │ Buscar:                             │
  │ - Campos de primer nivel            │
  │ - Arrays anidados                   │
  │ - Referencias a usuarios/customers  │
  │ - Timestamps                        │
  │ - Estructura de IDs                 │
  └─────────────────────────────────────┘
  ↓
FASE 2: DISEÑO (30-40 min)
  ↓
  ┌──────────────────────────────────────────────┐
  │ Decisiones de normalización:                 │
  │                                              │
  │ Para cada array:                             │
  │   ¿Cardinalidad alta (>50)? → Tabla         │
  │   ¿Tiene FK? → Tabla                         │
  │   ¿Se consulta en WHERE? → Tabla            │
  │   Sino → JSONB                               │
  │                                              │
  │ Para cada campo:                             │
  │   ¿Es user/customer? → FK a public.*        │
  │   ¿Es timestamp? → TIMESTAMP                │
  │   ¿Estructura variable? → JSONB             │
  │   Sino → Columna simple                      │
  └──────────────────────────────────────────────┘
  ↓
  ┌──────────────────────────────────────────────┐
  │ Diseñar schema SQL:                          │
  │                                              │
  │ 1. Tabla main con PK semántica              │
  │ 2. Tablas relacionadas (1:N)                │
  │ 3. Foreign Keys a public.*                  │
  │ 4. Índices en columnas de búsqueda          │
  └──────────────────────────────────────────────┘
  ↓
FASE 3: IMPLEMENTACIÓN (60-90 min)
  ↓
  ┌──────────────────────────────────────────────┐
  │ 1. dbsetup.py                                │
  │    Agregar creación de schema y tablas      │
  └──────────────────────────────────────────────┘
  ↓
  ┌──────────────────────────────────────────────┐
  │ 2. config.py                                 │
  │    Agregar entrada en COLLECTIONS            │
  └──────────────────────────────────────────────┘
  ↓
  ┌──────────────────────────────────────────────┐
  │ 3. migrators/mi_coleccion.py                 │
  │    Implementar BaseMigrator                  │
  └──────────────────────────────────────────────┘
  ↓
FASE 4: VALIDACIÓN (15-20 min)
  ↓
  ┌──────────────────────────────────────────────┐
  │ python dbsetup.py              # Crear tablas│
  │ python mongomigra.py           # Migrar      │
  │                                              │
  │ Verificar:                                   │
  │ - Conteo de registros                        │
  │ - Foreign keys válidas                       │
  │ - Queries de prueba                          │
  └──────────────────────────────────────────────┘
```

### Ejemplo Real: lml_processes

**1. Documento MongoDB (simplificado)**:
```json
{
  "_id": "507f1f77bcf86cd799439011",
  "processNumber": "TR-2024-001",
  "customerId": "CUST001",
  "createdBy": {
    "user": {
      "id": "USR001",
      "email": "juan@ejemplo.com",
      "area": {"id": "AREA01", "name": "Operaciones"}
    }
  },
  "movements": [
    {"at": "2024-01-15T10:00:00Z", "to": "Aprobación"},
    {"at": "2024-01-16T14:30:00Z", "to": "Finalizado"}
  ],
  "initiatorFields": {
    "monto": {"id": "FLD001", "name": "Monto Total"}
  }
}
```

**2. Decisiones de Normalización**:

| Elemento | Decisión | Razón |
|----------|----------|-------|
| `_id` | → `process_id VARCHAR(255) PK` | Semantic naming |
| `customerId` | → FK a `public.customers` | Entidad compartida |
| `createdBy.user` | → FK a `public.users` | Entidad compartida + normalizar area |
| `movements[]` | → Tabla `lml_processes.movements` | Array grande, se consulta |
| `initiatorFields{}` | → Tabla `lml_processes.initiator_fields` | Dict dinámico, normalizable |

**3. Schema SQL Resultante**:
```sql
-- Tabla principal
CREATE TABLE lml_processes.main (
    process_id VARCHAR(255) PRIMARY KEY,
    process_number VARCHAR(255),
    customer_id VARCHAR(255) REFERENCES public.customers(id),
    created_by_user_id VARCHAR(255) REFERENCES public.users(id),
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Tabla relacionada 1:N
CREATE TABLE lml_processes.movements (
    id SERIAL PRIMARY KEY,
    process_id VARCHAR(255) REFERENCES lml_processes.main(process_id),
    movement_at TIMESTAMP,
    destination_type VARCHAR(50)
);

-- Campos dinámicos
CREATE TABLE lml_processes.initiator_fields (
    id SERIAL PRIMARY KEY,
    process_id VARCHAR(255) REFERENCES lml_processes.main(process_id),
    field_key VARCHAR(255),
    field_id VARCHAR(255),
    field_name VARCHAR(255)
);
```

### Patrones Comunes de Identificación

**Tabla de referencia rápida**:

| Patrón en MongoDB | Acción | Destino PostgreSQL |
|-------------------|--------|--------------------|
| `{user: {id, email, ...}}` | Normalizar usuario completo | FK a `public.users` |
| `customerId: "..."` | FK simple | FK a `public.customers` |
| `movements: [{...}, {...}]` | Array grande | Tabla relacionada |
| `config: {key: val, ...}` | Estructura variable | JSONB column |
| `createdAt: ISODate(...)` | Timestamp | `TIMESTAMP` column |
| `deleted: true` | Boolean | `BOOLEAN` column |
| `tags: ["tag1", "tag2"]` | Array simple | `TEXT[]` o tabla |

---

## Agregar Nueva Colección

### Checklist Completo

```
┌────────────────────────────────────────────────────────────────┐
│           CHECKLIST: AGREGAR COLECCIÓN NUEVA                    │
└────────────────────────────────────────────────────────────────┘

□ PASO 1: Exportar y analizar
  □ python export_sample.py <collection_name> 200
  □ Revisar samples/<collection>_sample.json
  □ Identificar:
    □ Entidades compartidas (users, customers, etc.)
    □ Arrays que requieren normalización
    □ Campos JSONB vs columnas simples
    □ Primary key semántica

□ PASO 2: Diseñar schema PostgreSQL
  □ Definir nombre de schema (ej: lml_nueva_coleccion)
  □ Diseñar tabla main con PK semántica
  □ Diseñar tablas relacionadas (1:N)
  □ Definir Foreign Keys a public.*
  □ Identificar columnas para índices

□ PASO 3: Actualizar config.py
  □ Agregar entrada en COLLECTIONS:
    ```python
    "mi_coleccion_mesa4core": {
        "postgres_schema": "mi_coleccion",
        "primary_key": "mi_id",  # Semantic!
        "shared_entities": ["users", "customers"],
        "description": "..."
    }
    ```

□ PASO 4: Extender dbsetup.py
  □ Agregar función setup_<mi_coleccion>_schema()
  □ Incluir:
    □ CREATE SCHEMA IF NOT EXISTS
    □ CREATE TABLE para main
    □ CREATE TABLE para cada relacionada
    □ Foreign Keys apropiadas
  □ Llamar función desde main()

□ PASO 5: Implementar migrador
  □ Crear migrators/mi_coleccion.py
  □ Heredar de BaseMigrator
  □ Implementar 5 métodos abstractos:
    □ extract_shared_entities()
    □ extract_data()
    □ insert_batches()
    □ initialize_batches()
    □ get_primary_key_from_doc()
  □ Métodos privados de ayuda según necesidad

□ PASO 6: Testing inicial
  □ python dbsetup.py  # Crear tablas
  □ Verificar en psql que schemas existen
  □ python mongomigra.py  # Probar con 10-100 docs
  □ Revisar logs de errores

□ PASO 7: Validación de integridad
  □ Comparar conteos:
    □ MongoDB: db.<collection>.countDocuments({})
    □ PostgreSQL: SELECT COUNT(*) FROM <schema>.main
  □ Verificar Foreign Keys:
    □ No deben haber valores NULL en FKs obligatorias
    □ Todas las FKs deben tener registro padre
  □ Queries de prueba:
    □ Joins entre main y relacionadas
    □ Joins con public.users, public.customers

□ PASO 8: Optimización
  □ Medir tiempo de migración completa
  □ Ajustar BATCH_SIZE si es necesario
  □ Agregar índices para queries lentas
  □ Documentar en este archivo
```

### Código Ejemplo para Cada Paso

**PASO 3: config.py**
```python
COLLECTIONS = {
    # ... colecciones existentes ...
    
    "lml_nueva_coleccion_mesa4core": {
        "postgres_schema": "lml_nueva_coleccion",
        "primary_key": "nueva_id",  # ⚠️ Semantic, not "mongo_id"!
        "shared_entities": ["users", "customers", "areas"],
        "description": "Descripción breve de qué contiene"
    }
}
```

**PASO 4: dbsetup.py**
```python
def setup_lml_nueva_coleccion_schema(cursor, conn):
    """Crea schema y tablas para lml_nueva_coleccion."""
    print("\n🔧 Configurando schema 'lml_nueva_coleccion'...")
    
    # Crear schema
    cursor.execute("CREATE SCHEMA IF NOT EXISTS lml_nueva_coleccion;")
    
    # Tabla main
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_nueva_coleccion.main (
            nueva_id VARCHAR(255) PRIMARY KEY,  -- Semantic PK!
            campo1 VARCHAR(255),
            customer_id VARCHAR(255) REFERENCES public.customers(id),
            created_by_user_id VARCHAR(255) REFERENCES public.users(id),
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        );
    """)
    
    # Tabla relacionada ejemplo
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lml_nueva_coleccion.items (
            id SERIAL PRIMARY KEY,
            nueva_id VARCHAR(255) REFERENCES lml_nueva_coleccion.main(nueva_id),
            item_name VARCHAR(255),
            item_order INTEGER
        );
    """)
    
    conn.commit()
    print("✅ Schema 'lml_nueva_coleccion' configurado")

# En main(), agregar:
def main():
    # ... código existente ...
    setup_lml_nueva_coleccion_schema(cursor, conn)
    # ...
```

**PASO 5: migrators/mi_coleccion.py** (ver template completo en sección "Estructura de Código")

**PASO 7: Validación**
```bash
# En MongoDB
mongo --host <host> --eval "db.lml_nueva_coleccion_mesa4core.countDocuments({})"

# En PostgreSQL
psql -U <user> -d mesamongo -c "SELECT COUNT(*) FROM lml_nueva_coleccion.main;"

# Verificar Foreign Keys
psql -U <user> -d mesamongo -c "
SELECT COUNT(*) 
FROM lml_nueva_coleccion.main m
LEFT JOIN public.users u ON m.created_by_user_id = u.id
WHERE m.created_by_user_id IS NOT NULL AND u.id IS NULL;
"
# Output esperado: 0 (no debe haber FKs huérfanas)
```

---

## Testing

### Ejecución de Tests

Actualmente **no hay test suite unitaria tradicional**. El testing se basa en:

1. **Validación de Arquitectura**: Verificar que la migración preserva estructura
2. **Tests de Integridad**: Queries SQL que validan constraints
3. **Tests Manuales**: Comparación MongoDB vs PostgreSQL

**Comandos de validación**:

```bash
# 1. Migración completa de colección
python mongomigra.py
# → Seleccionar colección del menú
# → Observar logs sin errores
# → Verificar tiempo de ejecución

# 2. Verificar conteos
psql -U <user> -d mesamongo << EOF
SELECT 'lml_processes.main' as tabla, COUNT(*) FROM lml_processes.main
UNION ALL
SELECT 'lml_processes.movements', COUNT(*) FROM lml_processes.movements
UNION ALL
SELECT 'public.users', COUNT(*) FROM public.users;
EOF

# 3. Verificar integridad referencial
psql -U <user> -d mesamongo << EOF
-- Procesos sin usuario creador válido
SELECT COUNT(*)
FROM lml_processes.main m
LEFT JOIN public.users u ON m.created_by_user_id = u.id
WHERE m.created_by_user_id IS NOT NULL AND u.id IS NULL;
-- Output esperado: 0

-- Movimientos sin proceso padre
SELECT COUNT(*)
FROM lml_processes.movements mov
LEFT JOIN lml_processes.main m ON mov.process_id = m.process_id
WHERE m.process_id IS NULL;
-- Output esperado: 0
EOF
```

### Cobertura de Validación

| Aspecto | Método de Testing | Criterio de Éxito |
|---------|-------------------|-------------------|
| Conteo de registros | Comparar `COUNT(*)` Mongo vs PG | Diferencia < 1% |
| Foreign Keys | Query con LEFT JOIN buscando NULLs | 0 registros huérfanos |
| Timestamps | Query con `created_at IS NULL` | 0 NULLs en campos obligatorios |
| Unicidad de PKs | Query con `GROUP BY HAVING COUNT(*) > 1` | 0 duplicados |
| Performance | Medir tiempo total de migración | Dentro de ±20% de baseline |

**Queries de validación estándar**:

```sql
-- Test 1: Contar duplicados en PK
SELECT process_id, COUNT(*) as cnt
FROM lml_processes.main
GROUP BY process_id
HAVING COUNT(*) > 1;
-- Output esperado: 0 rows

-- Test 2: Verificar que no hay FKs NULL cuando deberían existir
SELECT COUNT(*)
FROM lml_processes.main
WHERE customer_id IS NULL;
-- Output: Depende del negocio, revisar si es esperado

-- Test 3: Verificar rangos de fechas
SELECT MIN(created_at), MAX(created_at)
FROM lml_processes.main;
-- Output: Fechas deben ser razonables (no 1970 ni 2050)

-- Test 4: Verificar consistencia de relaciones 1:N
SELECT 
    m.process_id,
    COUNT(mov.id) as num_movements
FROM lml_processes.main m
LEFT JOIN lml_processes.movements mov ON m.process_id = mov.process_id
GROUP BY m.process_id
ORDER BY num_movements DESC
LIMIT 10;
-- Revisar que los procesos con muchos movimientos sean lógicos
```

### Filosofía de Testing

**Por qué NO tests unitarios tradicionales**:

1. **Naturaleza del proyecto**: Es una migración de datos, no lógica de negocio
2. **Datos reales son el test**: Los datos de producción revelan casos edge que unit tests no capturan
3. **Validación post-migración**: Es más importante verificar el resultado final que cada función individual

**Lo que SÍ hacemos**:

- ✅ Validación de arquitectura (schemas, tablas, FKs correctas)
- ✅ Tests de integridad referencial
- ✅ Comparación de volumetría
- ✅ Queries de smoke test

**Lo que NO hacemos (y por qué está bien)**:

- 🚫 Unit tests de cada función `_extract_*()` → Los datos reales son suficiente test
- 🚫 Mocks de MongoDB/PostgreSQL → Queremos probar contra las DBs reales
- 🚫 Coverage al 100% → No es el objetivo en este tipo de proyecto

---

## Configuración de Performance

### BATCH_SIZE = 2000

**Valor actual**: `config.py` define `BATCH_SIZE = 2000`

**Justificación técnica**:

```
BATCH_SIZE = Número de documentos procesados antes de hacer INSERT masivo

Trade-off fundamental:
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Más grande (5000+)          Más pequeño (500-)            │
│  ✅ Menos round-trips DB      ✅ Menos memoria RAM          │
│  ✅ Más rápido               ✅ Más seguro ante errores     │
│  🚫 Más memoria              🚫 Más round-trips             │
│  🚫 Riesgo de OOM            🚫 Más lento                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Mediciones reales** (lml_processes, ~129k docs):

| BATCH_SIZE | Tiempo Total | Docs/seg | Memoria Pico | Observaciones |
|------------|--------------|----------|--------------|---------------|
| 500 | ~25 min | ~86 | 150 MB | Muchos commits |
| 1000 | ~22 min | ~98 | 200 MB | Balanceado |
| **2000** | **~20 min** | **~107** | **280 MB** | **✅ Elegido** |
| 5000 | ~18 min | ~119 | 600 MB | Cerca del límite |

**Por qué 2000**:
1. Performance cercana al óptimo (solo 10% más lento que 5000)
2. Memoria segura (280 MB << 2 GB disponible)
3. Margen para colecciones más grandes en el futuro

### Tabla de Recomendaciones

| Situación | BATCH_SIZE Recomendado | Razón |
|-----------|------------------------|-------|
| Documentos pequeños (<5 KB) | 2000-5000 | Más docs caben en memoria |
| Documentos grandes (>50 KB) | 500-1000 | Evitar OOM |
| Colección gigante (>1M docs) | 1000-2000 | Balance tiempo/estabilidad |
| Testing/debugging | 100-500 | Feedback rápido |
| Máquina con poca RAM | 500-1000 | Prevención |

### Tuning Empírico

**Proceso para ajustar BATCH_SIZE**:

```python
# 1. Agregar logging de tiempo
import time

start = time.time()
for i in range(0, len(docs), BATCH_SIZE):
    # ... procesar batch ...
    elapsed = time.time() - start
    docs_per_sec = (i + BATCH_SIZE) / elapsed
    print(f"Docs procesados: {i}/{total} ({docs_per_sec:.1f} docs/seg)")

# 2. Experimentar con valores
# Probar: 500, 1000, 2000, 5000
# Registrar: tiempo, memoria (usar htop/task manager)

# 3. Elegir el valor donde:
# - Tiempo es < 110% del óptimo
# - Memoria es < 50% del disponible
# - Sin errores de OOM
```

**Concepto clave**: No siempre el más rápido es el mejor. Priorizar:
1. **Estabilidad** (no fallar por OOM)
2. **Tiempo razonable** (dentro de 20% del óptimo)
3. **Margen de seguridad** (para documentos más grandes inesperados)

---

## Troubleshooting

### Error: duplicate key value violates unique constraint

**Error completo**:
```
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "users_pkey"
DETAIL: Key (id)=(USR001) already exists.
```

**Causa**:
- Intentando insertar un usuario que ya existe en `public.users`
- Olvidaste agregar `ON CONFLICT DO NOTHING`

**Solución**:
```python
# ❌ Incorrecto
cursor.execute(
    "INSERT INTO public.users (id, email) VALUES (%s, %s)",
    (user_id, email)
)

# ✅ Correcto
cursor.execute(
    "INSERT INTO public.users (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
    (user_id, email)
)
```

**Prevención**:
- Todas las inserts en `public.*` deben tener `ON CONFLICT`
- Usar caché para evitar INSERTs redundantes

---

### Error: relation does not exist

**Error completo**:
```
psycopg2.errors.UndefinedTable: relation "lml_nueva_coleccion.main" does not exist
```

**Causa**:
- No ejecutaste `python dbsetup.py` antes de migrar
- Typo en el nombre del schema o tabla

**Solución**:
```bash
# 1. Verificar que el schema existe
psql -U <user> -d mesamongo -c "\dn"

# 2. Si no existe, ejecutar setup
python dbsetup.py

# 3. Verificar que las tablas se crearon
psql -U <user> -d mesamongo -c "\dt lml_nueva_coleccion.*"
```

**Prevención**:
- Siempre ejecutar `dbsetup.py` primero
- Agregar check en `mongomigra.py`:
  ```python
  def verify_schema_exists(cursor, schema_name):
      cursor.execute(
          "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
          (schema_name,)
      )
      if not cursor.fetchone():
          print(f"❌ Schema '{schema_name}' no existe. Ejecuta: python dbsetup.py")
          sys.exit(1)
  ```

---

### Error: 'NoneType' object has no attribute

**Error completo**:
```
AttributeError: 'NoneType' object has no attribute 'get'
Traceback:
  user_id = doc['createdBy']['user'].get('id')
```

**Causa**:
- Campo esperado no existe en el documento
- Anidamiento profundo sin checks de None

**Solución**:
```python
# ❌ Asume estructura siempre presente
user_id = doc['createdBy']['user'].get('id')

# ✅ Checks defensivos
created_by = doc.get('createdBy')
if not created_by:
    return None

user = created_by.get('user')
if not user:
    return None

user_id = user.get('id')
```

**Patrón recomendado**:
```python
def safe_get_nested(doc, *keys, default=None):
    """
    Obtiene valor anidado de forma segura.
    
    Ejemplo:
        safe_get_nested(doc, 'createdBy', 'user', 'id')
        # Equivale a: doc.get('createdBy', {}).get('user', {}).get('id')
    """
    result = doc
    for key in keys:
        if not isinstance(result, dict):
            return default
        result = result.get(key)
        if result is None:
            return default
    return result

# Uso
user_id = safe_get_nested(doc, 'createdBy', 'user', 'id')
```

---

### Performance lenta: Solo 50-100 docs/seg

**Síntomas**:
- Migración tarda horas en lugar de minutos
- Cada documento toma >100ms

**Diagnóstico**:
```python
import time

# Agregar timing a cada operación
t1 = time.time()
shared = migrator.extract_shared_entities(doc, cursor, caches)
t2 = time.time()
data = migrator.extract_data(doc, shared)
t3 = time.time()

print(f"extract_shared_entities: {(t2-t1)*1000:.1f}ms")
print(f"extract_data: {(t3-t2)*1000:.1f}ms")
```

**Causas comunes**:

1. **Sin caché de entidades**
   ```python
   # ❌ Problema: Procesa mismo usuario 1000 veces
   for doc in docs:
       process_user(doc['createdBy']['user'])  # INSERT cada vez
   
   # ✅ Solución: Usar caché
   for doc in docs:
       user_id = doc['createdBy']['user']['id']
       if user_id not in caches['users']:
           process_user(...)
           caches['users'].add(user_id)
   ```

2. **BATCH_SIZE muy pequeño**
   ```python
   # ❌ BATCH_SIZE = 10  → 12,900 commits para 129k docs
   # ✅ BATCH_SIZE = 2000 → 65 commits
   ```

3. **Índices faltantes en PostgreSQL**
   ```sql
   -- Agregar índices en columnas de búsqueda frecuente
   CREATE INDEX idx_users_email ON public.users(email);
   CREATE INDEX idx_main_customer ON lml_processes.main(customer_id);
   ```

4. **Commits muy frecuentes**
   ```python
   # ❌ Commit después de cada INSERT
   cursor.execute(...)
   conn.commit()  # Lentísimo!
   
   # ✅ Commit cada batch
   if count % BATCH_SIZE == 0:
       conn.commit()
   ```

**Optimizaciones medidas**:

| Optimización | Antes | Después | Mejora |
|--------------|-------|---------|--------|
| Agregar caché | 400 docs/min | 2000 docs/min | 5x |
| Aumentar batch 500→2000 | 22 min | 20 min | 10% |
| Índices en FKs | 20 min | 18 min | 10% |

---

### Foreign Key Violation

**Error completo**:
```
psycopg2.errors.ForeignKeyViolation: insert or update on table "main" violates foreign key constraint "main_created_by_user_id_fkey"
DETAIL: Key (created_by_user_id)=(USR999) is not present in table "users".
```

**Causa**:
- Intentando insertar FK antes que el registro padre exista
- Usuario no fue procesado en `extract_shared_entities()`

**Solución**:
```python
def extract_shared_entities(self, doc, cursor, caches):
    # ✅ SIEMPRE procesar usuarios ANTES de retornar IDs
    created_by_user_id = None
    if doc.get('createdBy'):
        created_by_user_id = self._process_user(
            doc['createdBy']['user'], 
            cursor, 
            caches
        )
        # ⚠️ Verificar que el usuario se insertó
        if created_by_user_id:
            cursor.execute(
                "SELECT id FROM public.users WHERE id = %s",
                (created_by_user_id,)
            )
            if not cursor.fetchone():
                print(f"⚠️ Usuario {created_by_user_id} no existe después de procesar")
                created_by_user_id = None
    
    return {'created_by_user_id': created_by_user_id}
```

**Debugging**:
```sql
-- Encontrar registros con FKs inválidas ANTES de la migración
SELECT m.process_id, m.created_by_user_id
FROM lml_processes.main m
LEFT JOIN public.users u ON m.created_by_user_id = u.id
WHERE m.created_by_user_id IS NOT NULL AND u.id IS NULL
LIMIT 10;
```

---

## Métricas y Recursos

### Performance Actual

**Tabla de métricas medidas**:

| Colección | Documentos | Tiempo | Docs/seg | Memoria | Complejidad |
|-----------|------------|--------|----------|---------|-------------|
| lml_processes | ~129,000 | ~20 min | ~107 | 280 MB | Alta (5 tablas) |
| lml_listbuilder | ~200 | <1 min | N/A | <50 MB | Alta (9 tablas) |

**Desglose lml_processes**:

| Fase | Tiempo | % Total | Descripción |
|------|--------|---------|-------------|
| Conexión DB | ~5 seg | <1% | Conectar Mongo + PostgreSQL |
| Procesamiento | ~19 min | 95% | Loop principal de migración |
| Final commit | ~30 seg | 4% | Último batch + índices |

### Proyección para Ejecución Completa

Asumiendo 8 colecciones total con volumetrías variadas:

| Colección (estimado) | Docs | Tiempo Est. | Estado |
|----------------------|------|-------------|--------|
| lml_processes | 129k | 20 min | ✅ Migrado |
| lml_listbuilder | 200 | <1 min | ✅ Migrado |
| lml_clients | ~50k | ~8 min | 🔧 Pendiente |
| lml_providers | ~30k | ~5 min | 🔧 Pendiente |
| lml_products | ~100k | ~15 min | 🔧 Pendiente |
| lml_invoices | ~200k | ~30 min | 🔧 Pendiente |
| lml_reports | ~10k | ~2 min | 🔧 Pendiente |
| lml_settings | ~500 | <1 min | 🔧 Pendiente |
| **TOTAL** | **~520k** | **~81 min** | **2/8 done** |

**Nota**: Proyecciones basadas en ratio de ~107 docs/seg para colecciones complejas.

### Configuración Futura para n8n

**Objetivo**: Sincronización automática cada N horas/días.

**Arquitectura propuesta**:
```
n8n Workflow:
  ┌────────────────────────────────────┐
  │  Trigger: Cron (ej: cada 6 horas)  │
  └───────────────┬────────────────────┘
                  │
  ┌───────────────▼────────────────────┐
  │  Execute: python mongomigra.py     │
  │  (con modo batch no-interactivo)   │
  └───────────────┬────────────────────┘
                  │
  ┌───────────────▼────────────────────┐
  │  Parse output logs                 │
  │  - Documentos procesados           │
  │  - Tiempo total                    │
  │  - Errores si los hay              │
  └───────────────┬────────────────────┘
                  │
  ┌───────────────▼────────────────────┐
  │  Enviar notificación               │
  │  - Email/Slack con resultado       │
  │  - Alertas si hay errores          │
  └────────────────────────────────────┘
```

**Modificaciones requeridas en mongomigra.py**:
```python
# Agregar argumento CLI para modo batch
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--collection', help='Nombre de colección a migrar')
parser.add_argument('--all', action='store_true', help='Migrar todas las colecciones')
parser.add_argument('--quiet', action='store_true', help='Modo silencioso')
args = parser.parse_args()

if args.all:
    for collection_name in config.COLLECTIONS.keys():
        migrate_collection(collection_name, quiet=args.quiet)
elif args.collection:
    migrate_collection(args.collection, quiet=args.quiet)
else:
    # Modo interactivo actual
    show_collection_menu()
```

### Historial de Versiones

| Versión | Fecha | Cambios Principales |
|---------|-------|---------------------|
| v1.0 | 2025-10-30 | POC inicial: migración monolítica de lml_processes |
| v2.0 | 2025-11-05 | Refactorización: nomenclatura semántica (process_id vs mongo_id) |
| v3.0 | 2025-11-15 | Arquitectura multi-colección: BaseMigrator + carga dinámica |
| v3.1 | 2025-01-19 | Segunda colección (lml_listbuilder) + documentación completa |

### Recursos Adicionales

**Documentación PostgreSQL**:
- Foreign Keys: https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-FK
- JSONB: https://www.postgresql.org/docs/current/datatype-json.html
- Batch INSERT: https://www.psycopg.org/docs/extras.html#fast-execution-helpers

**Documentación MongoDB**:
- Extended JSON: https://www.mongodb.com/docs/manual/reference/mongodb-extended-json/
- PyMongo Cursor: https://pymongo.readthedocs.io/en/stable/api/pymongo/cursor.html

**Convenciones y Patrones**:
- Strategy Pattern: https://refactoring.guru/design-patterns/strategy/python
- Repository Pattern: https://martinfowler.com/eaaCatalog/repository.html

**Herramientas útiles**:
- DBeaver: Cliente SQL multi-plataforma (útil para inspeccionar PostgreSQL)
- MongoDB Compass: GUI para explorar colecciones MongoDB
- pgAdmin: Cliente oficial de PostgreSQL

---

## 🔧 Stack Tecnológico

### Tecnologías Core
- **Python 3.12**: Lenguaje de programación principal
- **pymongo**: Driver y cliente de MongoDB
- **psycopg2**: Adaptador de PostgreSQL
- **python-dotenv**: Gestión de variables de entorno

### Sistemas de Base de Datos
- **MongoDB** (Origen): Base de datos NoSQL orientada a documentos
- **PostgreSQL** (Destino): Base de datos SQL relacional

## 📊 Transformación del Modelo de Datos

### Estructura MongoDB (Original)
Los documentos en la colección `lml_processes_mesa4core` contienen objetos profundamente anidados:

```javascript
{
  _id: ObjectId("..."),
  processNumber: "12345",
  customerId: "CUST001",
  createdBy: {
    user: {
      id: "USR001",
      email: "usuario@ejemplo.com",
      firstname: "Juan",
      lastname: "Pérez",
      area: { id: "AREA01", name: "Operaciones" },
      subarea: { id: "SUB01", name: "Logística" },
      role: { id: "ROLE01", name: "Gerente" },
      groups: [{ id: "GRP01", name: "Administradores" }]
    }
  },
  movements: [
    { at: ISODate("..."), id: "MOV001", to: "destino" }
  ],
  initiatorFields: {
    campo1: { id: "FLD01", name: "Campo Uno" }
  }
}
```

### Estructura PostgreSQL (Transformada)

#### Entidades Compartidas (schema public)
```sql
public.users (
  id VARCHAR(255) PRIMARY KEY,
  email VARCHAR(255) UNIQUE,
  firstname VARCHAR(255),
  lastname VARCHAR(255),
  area_id VARCHAR(255) → public.areas(id),
  subarea_id VARCHAR(255) → public.subareas(id),
  role_id VARCHAR(255) → public.roles(id)
)

public.customers (
  id VARCHAR(255) PRIMARY KEY
)
```

#### Específico de Colección (schema lml_processes)
```sql
lml_processes.main (
  process_id VARCHAR(255) PRIMARY KEY,  -- Anteriormente mongo_id
  process_number VARCHAR(255),
  customer_id VARCHAR(255) → public.customers(id),
  created_by_user_id VARCHAR(255) → public.users(id),
  updated_by_user_id VARCHAR(255) → public.users(id),
  ...
)

lml_processes.movements (
  id SERIAL PRIMARY KEY,
  process_id VARCHAR(255) → lml_processes.main(process_id),  -- Anteriormente record_id
  movement_at TIMESTAMP,
  destination_id VARCHAR(255),
  destination_type VARCHAR(50)
)
```

### Convenciones de Nomenclatura Clave
Las mejoras recientes establecen patrones claros:

1. **Claves Primarias**: Usar nombres semánticos (`process_id` no `mongo_id`)
2. **Claves Foráneas**: Coincidir con nombres de claves primarias referenciadas (`process_id` no `record_id`)
3. **Consistencia**: La misma entidad se referencia de la misma forma en todos lados

## 📜 Scripts Actuales

### `config.py` - Gestión de Configuración
Centraliza toda la configuración no sensible:

```python
# Detalles de conexión MongoDB
MONGO_URI  # Construido desde variables de entorno
MONGO_DATABASE_NAME = "mesa4core"
MONGO_SOURCE_COLLECTION = "lml_processes_mesa4core"

# Detalles de conexión PostgreSQL
POSTGRES_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB'),  # "mesamongo"
    # ... otros parámetros de conexión
}

# Mapeos de nombres de tablas
TABLE_NAMES = { ... }

# Configuración de migración
POC_SCHEMA_NAME = "lml_processes"
BATCH_SIZE = 500  # Registros por inserción en lote
```

**Decisión de Diseño**: Separar la configuración de la lógica permite:
- Ajustes fáciles sin cambios de código
- Futura conversión a archivos de configuración (JSON/YAML)
- Documentación clara de los parámetros del sistema

### `mongomigra.py` - Motor de Migración
El script principal de migración implementa:

#### 1. Gestión de Conexiones
```python
def connect_to_mongo()
def connect_to_postgres()
```
Establecen conexiones con manejo de errores apropiado y configuración de timeouts.

#### 2. Creación de Schema
```python
def create_postgres_tables(pg_cursor, pg_conn)
```
Crea la estructura completa del schema híbrido. Actualmente usa `DROP TABLE CASCADE` para migraciones de pizarra limpia.

**Importante**: Esto es aceptable para POC pero debe refactorizarse para producción (ver Mejoras Futuras).

#### 3. Procesamiento de Entidades con Caché
```python
def process_user_data(user_obj, pg_cursor, caches)
def process_customer_data(customer_id, pg_cursor, caches)
```

**El Patrón de Caché**: Optimización crítica de rendimiento
- **Problema**: Sin caché, cada documento procesa usuarios redundantemente
- **Solución**: `set()` en memoria rastrea entidades ya procesadas
- **Impacto**: Mejora de velocidad de ~5x (2,000 docs/min vs. 400 docs/min)

```python
caches = {
    'users': set(),
    'customers': set(),
    # ... otras entidades
}

# Ruta rápida: búsqueda O(1)
if user_id in caches['users']:
    return user_id  # Saltar operación de base de datos

# Ruta lenta: Insertar en base de datos
pg_cursor.execute("INSERT INTO public.users ...")
caches['users'].add(user_id)  # Recordar para la próxima vez
```

#### 4. Migración por Lotes
```python
def migrate_collection(mongo_db, pg_cursor, pg_conn)
```

**Estrategia de Procesamiento por Lotes**:
- Acumula registros en listas en memoria (ej., `main_batch`, `movements_batch`)
- Inserta en lotes de 500 usando `executemany()`
- Hace commit de cada lote a la base de datos

**¿Por qué por Lotes?**
- `INSERT` único: ~10-50ms por registro = 20 registros/segundo
- `INSERT` por lotes: ~100ms por 500 registros = 5,000 registros/segundo
- Overhead de red reducido en ~99%

```python
if count % BATCH_SIZE == 0:
    pg_cursor.executemany(sql, main_batch)  # Inserción masiva
    main_batch = []  # Limpiar para el siguiente lote
    pg_conn.commit()
```

## 🐛 Problemas Resueltos

### 1. Timeout de Red Durante Migraciones Largas
**Problema**: Timeout del cursor de MongoDB después de 30 minutos de inactividad

**Error**:
```
pymongo.errors.NetworkTimeout: 10.100.20.142:27017: timed out
```

**Solución**: Agregado `no_cursor_timeout=True` a la creación del cursor
```python
documents_to_migrate = source_collection.find(no_cursor_timeout=True)
```

**Nota**: Mejora pendiente es usar sesiones explícitas para control completo de timeout.

### 2. Sobrecarga de Salida en Consola
**Problema**: Cada documento procesado creaba una nueva línea, haciendo los logs ilegibles

**Solución**: Retorno de carro con flush para actualizaciones en una sola línea
```python
print(f"\r   -> Documentos procesados: {count}/{total_docs}", end="", flush=True)
```
- `\r` - Retorna el cursor al inicio de la línea
- `end=""` - Previene salto de línea
- `flush=True` - Fuerza salida inmediata (requerido para terminales bash)

### 3. Cuello de Botella de Rendimiento
**Problema**: Ejecución inicial procesaba solo 400 documentos/minuto

**Causa Raíz**: `process_user_data()` hacía 3-5 llamadas a la base de datos por documento, incluso para usuarios repetidos

**Solución**: Implementado caché en memoria (ver Patrón de Caché arriba)

**Resultado**: Rendimiento mejorado a 2,000 documentos/minuto

### 4. Riesgo de Duplicación de Datos
**Problema**: Re-ejecutar el script podría crear registros duplicados

**Solución**: Cláusula `ON CONFLICT DO NOTHING` en todas las inserciones
```python
INSERT INTO public.users (...) VALUES (...)
ON CONFLICT (id) DO NOTHING;
```
Esto hace el script **idempotente**: seguro para ejecutar múltiples veces.

## ✅ Estado Actual

### Qué Está Funcionando
- ✅ Migración completa de la colección `lml_processes_mesa4core` (123,084 documentos)
- ✅ Arquitectura de schema híbrido implementada
- ✅ Rendimiento optimizado con caché y procesamiento por lotes
- ✅ Relaciones de claves foráneas apropiadas establecidas
- ✅ Migración idempotente (segura para re-ejecutar)
- ✅ Convenciones de nomenclatura semántica (`process_id` vs `mongo_id`)

### Resultados Verificados
- Base de datos: `mesamongo` creada y poblada
- Schema: `public` contiene 7 tablas de entidades compartidas
- Schema: `lml_processes` contiene 5 tablas específicas de colección
- Integridad de datos: Todas las claves foráneas referencian apropiadamente las tablas padre

## 🔮 Próximos Pasos

### Inmediatos (Requeridos Antes de la Siguiente Colección)

1. **Separar Setup de Migración**
   ```
   Actual:     mongomigra.py (crea tablas + migra datos)
   Requerido:  setup_database.py (crea tablas UNA VEZ)
               mongomigra.py (solo migra datos)
   ```
   **Por qué**: `DROP TABLE CASCADE` destruye datos de colecciones previas

2. **Implementar Sistema de Reglas de Migración**
   Definir reglas específicas por colección en `config.py`:
   ```python
   COLLECTION_RULES = {
       "lml_processes_mesa4core": {
           "primary_key_name": "process_id",
           "target_schema": "lml_processes",
           "shared_entities": ["users", "customers"],
           # ...
       }
   }
   ```

3. **Manejar Timeouts de Sesión de MongoDB**
   Implementar gestión explícita de sesión para prevenir advertencia de timeout de 30 minutos:
   ```python
   with mongo_client.start_session() as session:
       documents_to_migrate = source_collection.find(
           no_cursor_timeout=True,
           session=session
       )
   ```

### Mejoras Futuras

1. **Soporte Multi-Colección**
   - Descubrimiento/listado de colecciones
   - Migración paralela de colecciones independientes
   - Seguimiento de progreso y reanudación

2. **Validación de Datos**
   - Análisis de schema pre-migración
   - Verificaciones de integridad de datos post-migración
   - Reconciliación de conteo de registros

3. **Manejo de Errores**
   - Recuperación elegante de fallos
   - Logging detallado de errores
   - Mecanismos de rollback

4. **Monitoreo y Reportes**
   - Dashboard de progreso de migración
   - Métricas de rendimiento
   - Reportes de calidad de datos

## 🔑 Comandos Útiles

### Configuración del Entorno
```bash
# Crear entorno virtual
python -m venv mongomigra

# Activar (Windows)
mongomigra\Scripts\activate

# Activar (Linux/Mac)
source mongomigra/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### Operaciones de Base de Datos
```bash
# Ejecutar migración
python mongomigra.py

# Verificar schema de PostgreSQL
psql -U <usuario> -d mesamongo -c "\dn"

# Verificar tablas en schema
psql -U <usuario> -d mesamongo -c "\dt lml_processes.*"

# Contar registros migrados
psql -U <usuario> -d mesamongo -c "SELECT COUNT(*) FROM lml_processes.main;"
```

### Desarrollo
```bash
# Agregar nueva dependencia
pip install <paquete>
pip freeze > requirements.txt

# Actualizar configuración
# Editar .env para secretos
# Editar config.py para parámetros no sensibles
```

## 🔐 Configuración del Entorno

### Estructura de `.env`
```ini
# MongoDB
MONGO_HOST=
MONGO_PORT=
MONGO_USER=
MONGO_PASSWORD=
MONGO_AUTH_SOURCE=

# PostgreSQL
POSTGRES_DB=mesamongo
POSTGRES_HOST=
POSTGRES_PORT=
POSTGRES_USER=
POSTGRES_PASSWORD=
```

**Nota de Seguridad**: Nunca hacer commit de `.env` al control de versiones. Usar plantilla `.env.example` para compartir con el equipo.

## 📝 Principios de Diseño Aplicados

### 1. Única Fuente de Verdad
Las entidades compartidas viven en el schema `public`, referenciadas por todos los schemas de colección vía claves foráneas.

### 2. Idempotencia
Todas las operaciones usan `ON CONFLICT DO NOTHING` para manejar re-ejecuciones de forma segura.

### 3. Rendimiento Primero
Operaciones de caché y por lotes minimizan viajes de ida y vuelta a la base de datos.

### 4. Claridad Semántica
Los nombres reflejan significado de negocio (`process_id`) no origen técnico (`mongo_id`).

### 5. Separación de Responsabilidades
- `config.py` - Configuración
- `mongomigra.py` - Lógica de migración
- `.env` - Secretos

### 6. Arquitectura A Prueba de Futuro
El diseño de schema híbrido escala a múltiples colecciones sin conflictos.

## 🎓 Lecciones Aprendidas

### Insights Técnicos
1. **Procesamiento por Lotes**: Mejora de rendimiento de 250x sobre fila por fila
2. **Caché en Memoria**: Esencial para búsquedas de entidades repetidas
3. **Timeouts de Cursor**: Operaciones de larga duración necesitan manejo explícito de timeout
4. **Claves Foráneas**: Refuerzan integridad de datos pero requieren orden de inserción cuidadoso

### Insights Arquitectónicos
1. **Schemas Híbridos**: Lo mejor de dos mundos (organización + entidades compartidas)
2. **Nomenclatura Semántica**: Reduce carga cognitiva y mejora mantenibilidad
3. **Externalización de Configuración**: Habilita flexibilidad sin cambios de código
4. **Scripts Idempotentes**: Seguridad en desarrollo y producción

## 🔄 Historial de Cambios Importantes

### v2.0 - Refactorización de Nomenclatura Semántica
**Fecha**: 2025-11-05

**Cambios**:
- Renombrado de base de datos: `postgres` → `mesamongo`
- Renombrado de columna: `mongo_id` → `process_id`
- Renombrado de FK: `record_id` → `process_id` (en todas las tablas relacionadas)
- Movimiento de entidad: `customer_id` de columna simple a FK → `public.customers`

**Justificación**: Mejorar la claridad semántica y establecer patrones de nomenclatura consistentes para futuras colecciones.

### v1.0 - Implementación Inicial de POC
**Fecha**: 2025-10-30 (aproximado)

**Logros**:
- Migración exitosa de primera colección
- Implementación de arquitectura de schema híbrido
- Optimizaciones de rendimiento (caché + batching)
- Manejo de timeout de cursor

### Tecnologías Core
- **Python 3.12**: Lenguaje de programación principal
- **pymongo**: Driver y cliente de MongoDB
- **psycopg2**: Adaptador de PostgreSQL
- **python-dotenv**: Gestión de variables de entorno

### Sistemas de Base de Datos
- **MongoDB** (Origen): Base de datos NoSQL orientada a documentos
- **PostgreSQL** (Destino): Base de datos SQL relacional

---

## 📝 Comandos Útiles de Referencia

### Configuración del Entorno
```bash
# Crear entorno virtual
python -m venv mongomigra

# Activar (Windows)
mongomigra\Scripts\activate

# Activar (Linux/Mac)
source mongomigra/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### Operaciones de Base de Datos
```bash
# Setup inicial (ejecutar UNA VEZ)
python dbsetup.py

# Ejecutar migración
python mongomigra.py

# Verificar schemas de PostgreSQL
psql -U <usuario> -d mesamongo -c "\dn"

# Verificar tablas en schema
psql -U <usuario> -d mesamongo -c "\dt lml_processes.*"

# Contar registros migrados
psql -U <usuario> -d mesamongo -c "SELECT COUNT(*) FROM lml_processes.main;"
```

### Desarrollo
```bash
# Exportar sample para análisis
python export_sample.py <collection_name> 200

# Analizar estructura de colección
python analyze_listbuilder.py

# Agregar nueva dependencia
pip install <paquete>
pip freeze > requirements.txt
```

---

## 🎓 Lecciones Aprendidas

### Insights Técnicos
1. **Procesamiento por Lotes**: Mejora de rendimiento de 250x sobre fila por fila
2. **Caché en Memoria**: Esencial para búsquedas de entidades repetidas (mejora 5x)
3. **Timeouts de Cursor**: Operaciones de larga duración necesitan `no_cursor_timeout=True`
4. **Claves Foráneas**: Refuerzan integridad de datos pero requieren orden de inserción cuidadoso

### Insights Arquitectónicos
1. **Schemas Híbridos**: Lo mejor de dos mundos (organización + entidades compartidas)
2. **Nomenclatura Semántica**: Reduce carga cognitiva y mejora mantenibilidad
3. **Externalización de Configuración**: Habilita flexibilidad sin cambios de código
4. **Scripts Idempotentes**: Seguridad en desarrollo y producción

### Patrones que Funcionaron Bien
- ✅ Strategy Pattern para migradores (BaseMigrator + implementaciones)
- ✅ Carga dinámica de módulos (evita modificar mongomigra.py)
- ✅ Caché simple con `set()` (O(1) lookups)
- ✅ Batch processing con `executemany()`

### Errores Comunes Evitados
- 🚫 NO usar `DROP TABLE CASCADE` en producción
- 🚫 NO asumir que todos los campos existen (usar `.get()`)
- 🚫 NO hacer commit después de cada INSERT
- 🚫 NO usar nombres técnicos (`mongo_id`) cuando hay nombres semánticos mejores

---

## 📋 Principios de Diseño Aplicados

### 1. Única Fuente de Verdad
Las entidades compartidas viven en el schema `public`, referenciadas por todos los schemas de colección vía claves foráneas.

### 2. Idempotencia
Todas las operaciones usan `ON CONFLICT DO NOTHING` para manejar re-ejecuciones de forma segura.

### 3. Rendimiento Primero
Operaciones de caché y por lotes minimizan viajes de ida y vuelta a la base de datos.

### 4. Claridad Semántica
Los nombres reflejan significado de negocio (`process_id`) no origen técnico (`mongo_id`).

### 5. Separación de Responsabilidades
- `config.py` - Configuración
- `dbsetup.py` - Setup de estructura
- `mongomigra.py` - Orquestación de migración
- `migrators/*.py` - Lógica específica por colección
- `.env` - Secretos

### 6. Arquitectura A Prueba de Futuro
El diseño de schema híbrido escala a múltiples colecciones sin conflictos.

---

## 🔄 Historial de Versiones

| Versión | Fecha | Cambios Principales |
|---------|-------|---------------------|
| v1.0 | 2025-10-30 | POC inicial: migración monolítica de lml_processes |
| v2.0 | 2025-11-05 | Refactorización: nomenclatura semántica (process_id vs mongo_id) |
| v3.0 | 2025-11-15 | Arquitectura multi-colección: BaseMigrator + carga dinámica |
| v3.1 | 2025-01-19 | Segunda colección (lml_listbuilder) + documentación completa |

---

## 🚀 Próximos Pasos

### Inmediatos
1. ✅ Separar setup de migración (dbsetup.py ≠ mongomigra.py) - COMPLETADO
2. ✅ Sistema de carga dinámica de migradores - COMPLETADO
3. 🔧 Migrar siguiente colección (TBD por prioridad de negocio)
4. 🔧 Implementar tests de integridad automatizados

### Mejoras Futuras
1. **Soporte Multi-Colección Paralelo**
   - Migración paralela de colecciones independientes
   - Seguimiento de progreso y reanudación

2. **Validación Automatizada**
   - Análisis de schema pre-migración
   - Verificaciones de integridad post-migración
   - Reconciliación de conteo de registros

3. **Manejo de Errores Robusto**
   - Recuperación elegante de fallos
   - Logging detallado de errores
   - Mecanismos de rollback

4. **Integración con n8n**
   - Modo batch no-interactivo
   - Sincronización programada
   - Notificaciones automáticas

---

## 📚 Estructura de `.env`

```ini
# MongoDB
MONGO_HOST=
MONGO_PORT=
MONGO_USER=
MONGO_PASSWORD=
MONGO_AUTH_SOURCE=

# PostgreSQL
POSTGRES_DB=mesamongo
POSTGRES_HOST=
POSTGRES_PORT=
POSTGRES_USER=
POSTGRES_PASSWORD=
```

**⚠️ Nota de Seguridad**: Nunca hacer commit de `.env` al control de versiones. Usar plantilla `.env.example` para compartir con el equipo.

---

**Última Actualización**: 2025-01-19  
**Versión Actual**: v3.1 (Arquitectura multi-colección + documentación completa)  
**Estado**: 2/8 colecciones migradas, sistema listo para escalar  
**Próximo Hito**: Migrar colección #3 siguiendo el workflow documentado  
**Colecciones Migradas**: 1 de ~N (pendiente determinar total)