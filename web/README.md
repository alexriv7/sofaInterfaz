# SOFA Manager Web (Fase 2)

Web app en React + Firebase que comparte datos con la app de escritorio
(`interfaz_sofa_ctk.py`): mismas notas, mismos grupos, misma base de datos.

- **Login** con email/contraseña (Firebase Authentication), registro y recuperación de contraseña.
- **Biblioteca de ejemplos**: búsqueda y filtros por carpeta y tipo (`.scn`, `.py`, `.xml`).
- **Notas colaborativas** por ejemplo, en tiempo real, con respuestas, edición y borrado de las propias.
- **Grupos**: crear, añadir/quitar miembros, salir, eliminar, y elegir el grupo activo para las notas.

## Cómo encaja con la app de escritorio

| Ruta en Realtime Database             | Quién escribe            |
|---------------------------------------|--------------------------|
| `sofa_examples/{ejemplo}`             | Escritorio (al cargar los ejemplos) |
| `sofa_comments/{ejemplo}/{id}`        | Escritorio y web         |
| `sofa_groups/{id}`                    | Escritorio y web         |
| `sofa_group_comments/{grupo}/{ejemplo}/{id}` | Escritorio y web  |
| `sofa_users/{uid}`, `sofa_usernames/{usuario}` | Web (registro)  |

La identidad compartida es el **nombre de usuario**: regístrate en la web con el mismo
usuario que tienes en la app de escritorio (`current_user` en `sofa_config.json`) y verás
tus grupos y podrás editar tus notas. La web no puede leer tu disco, así que la biblioteca
la publica la app de escritorio cada vez que carga la carpeta de ejemplos.

## Puesta en marcha (Windows)

Requisitos: [Node.js 20+](https://nodejs.org).

1. **Firebase Console** (mismo proyecto que usa el escritorio):
   - *Authentication → Sign-in method*: habilita **Correo electrónico/contraseña**.
   - *Configuración del proyecto → Tus apps*: añade una **app web** (`</>`) y copia su configuración.
2. Configura las variables:
   ```powershell
   cd C:\Users\alexr\sofa_interface\src\web
   copy .env.example .env
   notepad .env
   ```
   `VITE_FIREBASE_DATABASE_URL` es la misma URL que `FIREBASE_DATABASE_URL` del `.env` del escritorio.
3. Instala y arranca:
   ```powershell
   npm install
   npm run dev
   ```
   Abre http://localhost:5173
4. **Publica las reglas de seguridad** (`database.rules.json`). Sin ellas la web no podrá
   leer ni escribir. Desde la consola: *Realtime Database → Reglas*, pega el contenido; o con la CLI:
   ```powershell
   npx firebase-tools login
   npx firebase-tools deploy --only database --project TU_PROYECTO
   ```
   La app de escritorio usa el Admin SDK (`firebase-key.json`) y no se ve afectada por las reglas.
5. Abre la app de escritorio una vez para que publique la biblioteca de ejemplos.

### Desplegar en Firebase Hosting (opcional)

```powershell
npm run build
npx firebase-tools deploy --only hosting --project TU_PROYECTO
```

### Probar en local con emuladores (opcional)

Pon `VITE_USE_EMULATORS=true` en `.env` y en otra terminal:
```powershell
npx firebase-tools emulators:start --only auth,database --project demo-sofa
```

## Estructura

```
web/
├── database.rules.json   reglas de seguridad de Realtime Database
├── firebase.json         hosting + reglas + emuladores
└── src/
    ├── firebase.js            inicialización
    ├── lib/paths.js           normalizePath (idéntico a _normalize_path de Python)
    ├── context/               sesión (AuthContext) y grupo activo (GroupContext)
    ├── components/            Layout, GroupPicker, Notes
    └── pages/                 Login, Library, ExampleDetail, Groups
```
