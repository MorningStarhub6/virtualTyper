# Virtual Typer for NVDA

A fun NVDA add-on with two features:

1. **Virtual typer**: a hidden notepad with up to 50 saved files. Nothing shows on screen. You only hear it.
2. **Auto typer**: types the clipboard text into any edit field (Notepad, Word, a browser), one key at a time, like a fast human typist, with keyboard sounds. It does not paste. You can pause it and resume where it stopped.

## Commands

You can change these in NVDA menu, Preferences, Input gestures, category "Virtual Typer".

- **NVDA+apostrophe**: open or close the virtual typer.
- **NVDA+Control+apostrophe**: type the clipboard into the focused app. Press it again to pause, and again to resume.
- **NVDA+Control+Shift+apostrophe**: stop auto typing and forget paused typing.

## Inside the virtual typer

While it is open, the keyboard goes to the virtual typer instead of the app underneath. Nothing ever appears on the screen.

- Type normally. Enter makes a new line and Tab types a tab.
- Arrows, Home, End, Page Up and Page Down move around. Control+Left and Control+Right move by word. Control+Home and Control+End go to the top and bottom.
- Add Shift to any of those to select text.
- Backspace and Delete erase. Add Control to erase a whole word.
- Control+A selects all. Control+C, Control+X and Control+V copy, cut and paste with the real Windows clipboard.
- Control+Z undoes and Control+Y (or Control+Shift+Z) redoes.
- **Control+S** saves. **Control+N** starts a new file.
- **Control+Tab** opens the list of saved files.
- **Control+Enter** closes the typer and auto-types its text (or just the selection) into the focused app.
- Escape closes the typer.
- F1 speaks a short help.

NVDA reading keys read the virtual typer while it is open:

- NVDA+Up arrow (laptop: NVDA+L): read the current line.
- NVDA+Shift+Up arrow (laptop: NVDA+Shift+S): read the selection.
- NVDA+Down arrow (laptop: NVDA+A): read from the caret to the end.
- NVDA+Numpad Delete (laptop: NVDA+Delete): line, column, word and character count.
- NVDA+T: the file's title, and whether it is saved.

All other NVDA commands work as usual. So do Alt+Tab, Windows key shortcuts, volume keys and Caps Lock.

## Saving

- With **auto save** on (the default), your file saves itself a few seconds after you type, and again when you close the typer or switch files.
- With auto save off, closing, starting a new file or opening another file asks: "Save changes?" Press Y to save, N to throw the changes away, or Escape to go back.
- If NVDA restarts, the file you had open comes back, including unsaved changes.
- Files are plain text in the `virtualTyper` folder inside your NVDA settings folder.

How new files get their title (in settings):

- **Date and time** when first saved.
- **First line of the text**, kept up to date as you edit. This is the default.
- **Ask me when saving**: a spoken prompt asks for the title. It starts filled in with the first line, so you can press Enter to keep it or just type a new one. With auto save on, you are asked when you close the file.

## The saved files list

Press Control+Tab in the virtual typer. The most recently saved file is first.

- Up and Down arrows, or Control+Tab and Control+Shift+Tab, move through the list. Home, End, Page Up and Page Down work too.
- Type a letter to jump to a title that starts with it.
- Enter opens the file.
- Delete deletes it, after asking Y or N.
- F2 renames it.
- NVDA+Up arrow also says when the file was saved.
- Escape goes back to your text.

When you have more files than the limit in settings, the oldest ones are deleted.

## Auto typer

- It waits until you let go of all modifier keys, so NVDA+Control does not turn letters into shortcuts. Holding any modifier key pauses typing.
- Escape stops it.
- If you switch to another window, it pauses by itself.

### Pause and resume

Press NVDA+Control+apostrophe while it types to pause. Press it again to resume. Before it continues, it reads the text just before your cursor and compares it with what it typed:

- If everything arrived, it continues from the next character.
- If the last few characters never arrived, it types them again.
- If a letter near the end came out wrong, it erases back to that point and retypes from there.
- If the text before the cursor doesn't match at all, for example because you moved the cursor, it tells you and doesn't type. Move back to the end of the typed text, or press the key again to continue anyway.

To throw away paused typing, press NVDA+Control+Shift+apostrophe.

New lines are typed with the Enter key. In chat apps such as WhatsApp, that sends each line as its own message.

## Keyboard sounds

Two packs are included: Keyboard 17 and Keyboard 18 (the default). Keys, space, enter and backspace each have their own sounds, and normal keys have 9 or 10 variations. Sounds can overlap, so fast typing doesn't cut them off.

By default the sounds only play while the auto typer is typing. A setting also plays them while you type in the virtual typer.

To add your own pack, put files named like `mypacktype1.ogg`, `mypacktype2.ogg`, `mypackspace.ogg`, `mypackenter.ogg` and `mypackdelete.ogg` in the `sounds` folder, then run (needs ffmpeg):

```powershell
python tools\convertSounds.py
```

## Settings

NVDA menu, Preferences, Settings, "Virtual Typer":

- **Save files automatically while typing**: on by default.
- **Number of files to keep**: 1 to 50, default 50.
- **Title for new files**: date and time, first line, or ask me.
- **Auto typing speed**: characters per second, 1 to 100, default 20.
- **Natural rhythm**: uneven speed and short pauses after spaces, punctuation and new lines.
- **Typing mistakes**: now and then, types a nearby wrong letter, then backspaces and fixes it. Off by default.
- **Keyboard sounds**: Off, Keyboard 17 or Keyboard 18. Choosing one plays a sample.
- **Keyboard sound volume**: 0 to 100, default 80.
- **Also play keyboard sounds when typing in the virtual typer**: off by default.

## Limits

- The virtual typer reads keys through the Windows keyboard layout. Normal layouts and dead keys work. Input methods that open a candidate window, such as Chinese or Japanese IME, do not.
- Checking where to resume needs an edit field that NVDA can read. If it can't read the field, the auto typer simply continues from where it stopped.
- The add-on does nothing on secure screens or the lock screen.
- Requires NVDA 2025.1 or later.

## Build

You need Python 3. From this folder run:

```powershell
python build.py
```

This creates `virtualTyper-1.1.0.nvda-addon`. Press Enter on it to install.

Run the tests with:

```powershell
python -m unittest discover -s tests -v
```
