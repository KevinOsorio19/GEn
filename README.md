# Gestión de combustible PROING

Plataforma web en español con Python, SQLite y JavaScript. Permite importar Excel, gestionar flota y parámetros versionados, analizar consumos, revisar alertas y exportar resultados.

## Instalar y ejecutar

Requiere Python 3.10 o posterior (probado con Python 3.12).

```sh
python3 -m venv .venv
```

Activar el entorno en macOS/Linux:

```sh
source .venv/bin/activate
```

En Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Instalar dependencias e iniciar:

```sh
python -m pip install -r requirements.txt
python -m backend.server
```

Abrir http://127.0.0.1:8765. Mantener el proceso abierto. Los datos se crean en `data/fuel.sqlite` y los originales en `data/originals/`. Reiniciar conserva los datos. Esta distribución empieza vacía.

## Subir a un repositorio

Descomprimir el ZIP y subir el contenido de la carpeta `gestion-combustible` a un repositorio, preferiblemente privado. No subir el ZIP como único archivo: deben verse `backend`, `web`, `tests` y `requirements.txt` en la raíz.

El paquete excluye bases de datos, Excel cargados, informes con datos reales, credenciales y archivos propios del equipo de desarrollo. `.gitignore` protege esos archivos ante futuras cargas con Git. Si se usa la carga manual del navegador, también hay que excluirlos manualmente.

Compartir el repositorio permite descargar y ejecutar el código en otro computador. No crea por sí solo un enlace web público. Esta aplicación necesita ejecutar Python; GitHub Pages por sí solo no ejecuta su servidor ni guarda SQLite.

## Uso

1. Cargar la flota permanente y los parámetros de líneas base.
2. Definir las vigencias de los parámetros por grupo.
3. Cargar cada mes Terpel, TSO eficiencia, TSO sumarizado y la base mensual de vehículos.
4. Procesar el mes, revisar alertas y comparar resultados con los originales.
5. Cerrar períodos únicamente después de validarlos.

Las correcciones requieren motivo y responsable. Se conservan originales y auditoría. Los períodos cerrados conservan sus resultados congelados.

## Cuentas y espacios independientes

El código incluye una implementación inicial de cuentas por invitación, sesiones y copias independientes por usuario. Este flujo aún requiere validación integral de acceso e aislamiento antes de exposición pública. Las pruebas incluidas se concentran en el motor, importaciones, documentos y parámetros.

Variables de configuración disponibles:

| Variable | Uso |
| --- | --- |
| `PORT` | Puerto, por defecto 8765 |
| `FUEL_DB` | Ruta de la base en modo local |
| `FUEL_MULTIUSER` | `1` para activar cuentas |
| `FUEL_ACCOUNTS_DIR` | Carpeta persistente para cuentas y perfiles |
| `FUEL_PUBLIC_URL` | Dirección HTTPS de acceso detrás de un proxy TLS |
| `FUEL_BIND` | Dirección de escucha, por defecto 127.0.0.1 |

El administrador se inicializa con `python -m backend.accounts --help`. La cuenta inicial se crea copiando una base existente junto con sus originales, y genera un enlace de registro de un solo uso. No hay contraseñas predeterminadas. El administrador puede invitar a otra persona desde su perfil. No versionar los enlaces de invitación ni el almacenamiento de cuentas.

Para compartir los datos existentes, transferirlos de forma privada junto con sus originales; no publicarlos en el repositorio. Conservar respaldos de toda la carpeta de almacenamiento. Compartir por internet requiere completar la configuración del servidor o acceso remoto; no se incluye un alojamiento contratado.

## Verificación

```sh
python -m unittest discover -s tests -q
```

Opcional, con Node instalado:

```sh
node --check web/app.js
```
