# Price Bot

Sigue los precios de videojuegos en varias tiendas españolas y te avisa por Telegram
cuando alguno baja del precio que tú marques.

No necesitas instalar nada. Python, el navegador y todo lo demás va dentro de esta carpeta.

---

## 1. Abrir la aplicación

**Windows** — doble clic en `price_bot_gui.exe`

**Linux** — doble clic en `price_bot_gui`, o desde una terminal:
```bash
./price_bot_gui
```

> **Windows puede avisarte** de que "Windows protegió tu PC". Es normal: la app no está
> firmada digitalmente, y eso cuesta dinero. Pulsa **Más información** → **Ejecutar de todas
> formas**.
>
> **Deja la carpeta entera junta.** El ejecutable necesita lo que hay a su lado; si mueves
> sólo el `.exe` a otro sitio, no arranca.

La primera vez tarda unos segundos más de lo normal. Es solo esa vez.

---

## 2. Conectar tu Telegram

Los avisos llegan por Telegram, así que hace falta un bot. Son dos minutos.

### a) Crear el bot y copiar el token

1. Abre Telegram y busca **@BotFather**
2. Envíale `/newbot`
3. Te pedirá un nombre y un nombre de usuario (tiene que acabar en `bot`)
4. Te responderá con una línea larga tipo `123456789:AAG...`. **Ese es el token.**

### b) Averiguar tu ID de chat

1. En Telegram, busca **@userinfobot**
2. Envíale cualquier mensaje
3. Te responde con tu `Id`, un número. **Ese es el ID de chat.**

### c) Meterlos en la aplicación

En Price Bot, pulsa el botón del **engranaje** → pestaña **Aplicación**:

- pega el token en **Token del bot de Telegram**
- pega el número en **ID de chat de Telegram**
- pulsa **Enviar mensaje de prueba**

Si te llega el mensaje a Telegram, ya está. Pulsa **Guardar**.

> **Importante:** antes de la prueba, abre una conversación con **tu** bot en Telegram y
> pulsa *Iniciar*. Telegram no deja que un bot escriba a alguien que no le ha hablado nunca,
> así que sin ese paso la prueba falla aunque el token sea correcto.

---

## 3. Añadir juegos

1. **Añadir producto** — nombre del juego, plataforma y el precio al que quieres que te avise
2. **Actualizar URLs** — busca solo la página de cada tienda. Tarda un poco: está abriendo
   las tiendas de verdad
3. **Iniciar bot** — comprueba los precios ahora mismo, y sigue comprobando cada X minutos

En **Ajustes → Bot** eliges cada cuánto comprueba y cómo se comportan los avisos.

---

## Cosas que conviene saber

**Tus datos son tuyos y locales.** Los juegos, los precios y el token se guardan en
`tracker.db`, dentro de esta carpeta. No se envía nada a ningún sitio salvo a tu propio bot
de Telegram.

**Cada uno tiene su copia.** Tu lista de juegos no la ve nadie más.

**Modo depuración**, en Ajustes → Aplicación, abre las ventanas del navegador para que veas
lo que hace. Está bien para curiosear o para entender un fallo; déjalo apagado para el uso
normal, va más rápido.

**Scraping en paralelo** consulta varias tiendas a la vez. Cada una abre su propio navegador
y consume memoria: si tu equipo tiene menos de 4 GB libres, bájalo a 2 o 3.

---

## Si algo va mal

**No arranca.** Comprueba que no has movido el ejecutable fuera de esta carpeta.

**No llegan los avisos.** Ve a Ajustes → Aplicación y pulsa *Enviar mensaje de prueba*: te
dirá si el problema son las credenciales. Si el mensaje sí llega pero no recibes alertas de
precio, es que ningún juego ha bajado todavía del precio que marcaste.

**Una tienda no da precio.** Pasa: las tiendas cambian sus páginas cada poco. La aplicación
lo marca en la fila y sigue con las demás.

**Todo lo demás.** En la carpeta `logs/` hay un fichero de texto con lo que ha ido pasando.
Mándaselo a quien te pasó la aplicación, ahí suele estar la respuesta.
