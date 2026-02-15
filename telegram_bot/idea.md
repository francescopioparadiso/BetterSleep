# 🛌 Sistema Gestione Camere (BetterSleep Bot)

## 1. Flusso di Benvenuto

Al primo avvio (`/start`), il bot presenta due opzioni principali:

* **🆕 Crea una nuova Camera**
* **🔑 Unisciti a una Camera esistente**

---

## 2. Logica dei Processi

### Caso A: Creazione Camera

1. **Richiesta Nome:**
   "Come vuoi chiamare la tua camera? (es. Stanza Master)"

2. **Richiesta Password:**
   "Scegli una password per far entrare i tuoi coinquilini."

3. **Salvataggio nel DB:**

   * Inserisce la riga in `bedrooms` (genera automaticamente un `bedroom_id`).
   * Restituisce all'utente:
     *"Camera creata! L'ID della tua stanza è **#105**. Condividilo con chi vuoi!"*

4. **Associazione Utente:**

   * Chiede l'**Username** dell’utente.
   * Crea il record in `users` con il `bedroom_id` appena generato.

---

### Caso B: Unione a Camera Esistente

1. **Richiesta ID Camera:**
   "Inserisci l'ID della camera a cui vuoi unirti."

2. **Richiesta Password:**
   "Inserisci la password della camera."

3. **Verifica nel DB:**

   * Il bot controlla se esiste una riga con quell'ID e quella password.
   * **Se corretto:** procede al punto 4.
   * **Se errato:** "ID o Password errati. Riprova."

4. **Associazione Utente:**

   * Chiede l'**Username**.
   * Crea o aggiorna l’utente collegandolo a quel `bedroom_id`.

---

## 3. Comando `/condividi` (Sistema di Invito)

Quando l'utente digita il comando:

1. **Verifica:**
   Controlla se l'utente è associato a un `bedroom_id`.

2. **Recupero Dati:**
   Se sì, cerca il `room_name` e la `room_password` nella tabella `bedrooms`.

3. **Risposta Formattata:**
   Invia i dettagli della camera in modo cliccabile o per copia-incolla:

   ```text
   Ecco i dettagli della tua camera:

   ID: `#105`
   Password: `supersegreta`
   ```

   Oppure come link cliccabile per Telegram:

   ```text
   Ecco i dettagli della tua camera:

   [ID: #105](https://t.me/BetterSleepBot?start=join_105)
   Password: `supersegreta`
   ```

---

