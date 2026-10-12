# VerdeListo

Aplicación web para que familias y estudiantes organicen sus alimentos, sepan cuáles usar primero y registren lo que aprovechan o desperdician.

## Ejecutar localmente

Requiere Python 3.10 o posterior.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abre <http://127.0.0.1:5000>. La base SQLite se crea automáticamente en `instance/foodwise.sqlite3`. Para guardar los datos en otro sitio, configura `FOODWISE_DATABASE` con la ruta deseada. El servidor no activa el modo debug salvo que `FLASK_DEBUG=1`.

La aplicación permite crear una cuenta e iniciar sesión. El nombre, correo y hash de contraseña se guardan en SQLite; las contraseñas no se almacenan en texto legible. Las sesiones usan una clave guardada localmente en `instance/secret_key`. En despliegues, configura `SECRET_KEY` con un valor secreto estable y, si el sitio usa HTTPS, `HTTPS_ONLY=1`. La sesión se cierra con el botón «Salir».

Los alimentos se asocian a la cuenta propietaria y no se comparten entre usuarios. Si la base ya tenía alimentos de una versión anterior sin cuentas, se conservan y se asignan a la primera cuenta que se registre.

## Funciones

- Inventario persistente de alimentos con categoría, cantidad y fecha de vencimiento.
- Filtros y prioridades para identificar alimentos que vencen pronto o ya vencieron.
- Registro de alimentos aprovechados o desperdiciados e historial de actividad.
- Ideas sencillas para cocinar, con coincidencias según los nombres de los alimentos registrados.
- Guion de presentación de cinco minutos y respuestas sugeridas para el hackathon.
- Diseño adaptable a teléfono y escritorio.

La aplicación registra actividad del usuario; no afirma que esos registros demuestren una reducción de emisiones o de desperdicio. Para validar impacto, el proyecto deberá comparar mediciones reales tomadas durante periodos definidos.

## API

| Método | Ruta | Uso |
| --- | --- | --- |
| `GET` | `/api/dashboard` | Alimentos activos y resumen |
| `GET` | `/api/session` | Consultar la sesión actual |
| `POST` | `/api/register` | Crear una cuenta e iniciar sesión |
| `POST` | `/api/login` | Iniciar sesión |
| `POST` | `/api/logout` | Cerrar sesión |
| `POST` | `/api/foods` | Agregar un alimento |
| `PATCH` | `/api/foods/<id>` | Marcar como `used` o `wasted` |
| `DELETE` | `/api/foods/<id>` | Quitar un alimento activo |
| `GET` | `/api/ideas` | Ideas de cocina y coincidencias |
| `GET` | `/api/history` | Últimos registros de aprovechamiento y desperdicio |

Para agregar un alimento se envía JSON con `name`, `category`, `quantity`, `unit` y `expires_on` (fecha ISO `AAAA-MM-DD`). Categorías admitidas: `Frutas`, `Verduras`, `Lácteos`, `Proteínas`, `Despensa` y `Otros`. Unidades: `unidad`, `kg`, `g`, `L`, `ml` y `paquete`.
