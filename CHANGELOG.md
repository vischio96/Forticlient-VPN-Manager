# Changelog

Formato basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versionamento [SemVer](https://semver.org/lang/it/).

## [1.0.0] - 2026-11-16

Prima versione pubblica.

### Aggiunto
- Icona nella system tray con pannello a comparsa (punto verde = almeno un tunnel connesso).
- Elenco di tutti i tunnel IPsec VPN e SSL VPN di FortiClient 7.4.x, con distinzione EMS / Personal e indicatore SAML.
- Ricerca istantanea per nome, server, tipo, origine e SAML.
- Raggruppamento per Tipo, Origine, Tipo + Origine; filtri IPsec / SSL / EMS / Personal; gruppo "Connessi".
- Connessione con un clic **senza finestra CMD**: le richieste di password, codice FortiToken o username
  di FortiClient compaiono come finestre di dialogo.
- Disconnessione dal pannello o dal menu della tray.
- Aggiornamento automatico dell'elenco (modifiche da EMS, nuovi tunnel personali).
- Finestra Impostazioni: avvio con Windows, notifiche pop-up (disattivate di default), intervallo di
  aggiornamento, controllo aggiornamenti, console di diagnostica.
- Controllo aggiornamenti da GitHub Releases con download e installazione in un clic.
- Installer Inno Setup per utente (senza diritti di amministratore) e versione portable.
