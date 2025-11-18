# mongo_to_postgre

Proyecto para realizar la migracion de una bbdd mongodb a postgre convirtiendola en relacional

# Estructura del proyecto

```
mongo_to_postgre/
├── config.py              # Ya existe, lo extendemos
├── db_setup.py            # Setup inicial (una sola vez)
├── mongomigra.py          # Solo migra datos
└── collections/           # Lógica específica por colección
    ├── lml_processes.py   # Logica de extraccion para esta coleccion especifica
    └── lml_listbuilder.py # Igual que la anterior, cada coleccion = 1 archivo
```
