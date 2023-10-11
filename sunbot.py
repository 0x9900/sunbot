#!/usr/bin/env python
# pylint: disable=unused-argument

"""
Send /start to initiate the conversation.
"""

import html
import json
import logging
import pathlib
import time
import traceback

import aiofiles
import httpx

from telegram import (
  InlineKeyboardButton,
  InlineKeyboardMarkup,
  Update,
  ForceReply
)
from telegram.constants import ParseMode
from telegram.ext import (
  Application,
  CallbackQueryHandler,
  CommandHandler,
  ContextTypes,
  ConversationHandler,
)
from typing import Optional

# Enable logging
logging.basicConfig(
  format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Stages
CONFIG_FILES = ("sunbot.conf", "~/.local/sunbot.conf", "/etc/sunbot.conf")
START_ROUTES = 1
SOURCE = "\nMore information at https://bsdworld.org/"
NOAA_URL = 'https://services.swpc.noaa.gov/'

RESOURCES = {
  "/dxcc": [
    "https://bsdworld.org/dxcc-stats.jpg",
    "Daily total number of spots for each continents"
  ],
  "/aindex": [
    "https://bsdworld.org/xaindex.jpg",
    "The A index show the fluctuations in the magnetic field."
  ],
  "/kpindex": [
    "https://bsdworld.org/kpindex.jpg",
    "Kp is an indicator of disturbances in the Earth's magnetic field."
  ],
  "/forecast": [
    "https://bsdworld.org/kpi-forecast.jpg",
    "Recently observed and a three day forecast of space weather conditions"
  ],
  "/enlil": [
    "https://bsdworld.org/enlil.mp4",
    "WSA-Enlil Solar Wind Prediction."
  ],
  "/flux": [
    "https://bsdworld.org/flux.jpg",
    "Solar radio flux at 10.7 cm (2800 MHz) is an indicator of solar activity"
  ],
  "/xray": [
    "https://bsdworld.org/xray_flux.jpg",
    ("X-ray emissions from the Sun are primarily associated with solar flares, which "
     "are sudden and intense releases of energy in the solar atmosphere.")
  ],
  "/proton": [
    "https://bsdworld.org/proton_flux.jpg",
    ("Proton Flux refers to the number of high-energy protons coming from the Sun "
     "and reaching the Earth's vicinity.")
  ],
  "/sunspot": [
    "https://bsdworld.org/ssn.jpg",
    "Daily index of sunspot activity."
  ],
  "/wind": [
    "https://bsdworld.org/solarwind.jpg",
    "Density, speed, and temperature of protons and electrons plasma."
  ],
  "/muf": [
    "https://bsdworld.org/muf.mp4",
    "Show the maximum usable frequency."
  ],
}


class Config:
  token: str = None
  developer_id: int | None = None

def load_config():
  for file_name in CONFIG_FILES:
    path = pathlib.Path(file_name).expanduser()
    if path.exists():
      break
  else:
    raise FileNotFoundError('Configuration file missing')
  with open(path, 'r', encoding="utf-8") as fdc:
    lines = (l.strip() for l in fdc)
    lines = (l for l in lines if not l.startswith('#'))
    for line in lines:
      key, val = line.split(':', 1)
      key = key.strip()
      val = val.strip()
      if key == 'token':
        Config.token = val
      elif key == 'developer_id':
        Config.developer_id = int(val)
      else:
        logging.warning("config error: %s", line)


def rid(timeout: Optional[int]=900) -> str:
  """Generate an id that will change every 900 seconds"""
  _id = int(time.time() / 900)
  return str(_id)

async def load_cache_file(url: str, filename: str, timeout: Optional[int]=3600):
  """download the content of an url and save it into a file"""
  file_path = pathlib.Path(filename)
  try:
    stats = file_path.stat()
    if stats.st_mtime + timeout < time.time():
      raise FileNotFoundError
  except FileNotFoundError:
    async with httpx.AsyncClient() as client:
      response = await client.get(url)
      async with aiofiles.open(file_path, mode='wb') as fdout:
        async for buffer in response.aiter_bytes(1024):
          await fdout.write(buffer)


async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """Send the flux graph"""
  message = update.effective_message
  user = message.from_user
  resource = RESOURCES[message.text]
  if resource[0].endswith('.jpg'):
    url = f"{resource[0]}?s={rid()}"
    await message.reply_photo(url, caption=f"{resource[1]}{SOURCE}")
  elif resource[0].endswith('.mp4'):
    url = f"{resource[0]}?s={rid(3600)}"
    await message.reply_video(url, caption=f"{resource[1]}{SOURCE}")
  else:
    raise TypeError('Unknown resource type')
  logger.info("User %s command %s - (%s).", user.first_name, message.text, url)
  return ConversationHandler.END


async def bands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """Send message on `/bands`."""
  user = update.message.from_user
  logger.info("User %s asking band informations.", user.first_name)
  keyboard = [
    [
      InlineKeyboardButton("North America", callback_data=str("NA")),
      InlineKeyboardButton("Europe", callback_data=str("EU")),
    ]
  ]
  reply_markup = InlineKeyboardMarkup(keyboard)
  await update.message.reply_text("Propagation: Choose a continent", reply_markup=reply_markup)
  return START_ROUTES

async def alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """download and send the NOAA alerts"""
  url = NOAA_URL + "text/wwv.txt"
  cache_file = "/tmp/alerts.json"
  await load_cache_file(url, cache_file)
  alert = []
  async with aiofiles.open(cache_file, mode='r', encoding="utf-8") as fdin:
    async for line in fdin:
      line = line.strip()
      if not line or line[0] == '#' or line.startswith(':Product'):
        continue
      line = line.replace(':Issued: ', 'Report from: ')
      alert.append(line)

  logger.info("User %s command %s",
              update.message.from_user.username,
              update.message.text)
  await update.message.reply_text('\n'.join(alert))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  """Send a message when the command /start is issued."""
  user = update.effective_user
  response = (
    f"Hi {user.mention_markdown()} and welcome.",
    "Use '/help' to see the list of commands.",
    "SunFluxBot developped by [W6BSD](https://0x9900.com/)"
  )
  await update.message.reply_markdown('\n'.join(response))


async def north_america(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """Show new choice of buttons"""
  query = update.callback_query
  await query.answer()
  keyboard = [
    [
      InlineKeyboardButton("CQZone 3", callback_data="3"),
      InlineKeyboardButton("CQZone 4", callback_data="4"),
      InlineKeyboardButton("CQZone 5", callback_data="4"),
    ],
    [
      InlineKeyboardButton("North America, all Zones", callback_data="@NA"),
    ]
  ]
  reply_markup = InlineKeyboardMarkup(keyboard)
  await query.edit_message_text(
      text="Choose a CQZone", reply_markup=reply_markup
  )
  return START_ROUTES


async def europe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """Show new choice of buttons"""
  query = update.callback_query
  await query.answer()
  keyboard = [
    [
     InlineKeyboardButton("CQZone 14", callback_data=str("14")),
     InlineKeyboardButton("CQZone 15", callback_data=str("15")),
     InlineKeyboardButton("CQZone 16", callback_data=str("16")),
     InlineKeyboardButton("CQZone 21", callback_data=str("20")),
    ],
    [
     InlineKeyboardButton("Europe, all Zones", callback_data=str("@EU")),
    ]
  ]
  reply_markup = InlineKeyboardMarkup(keyboard)
  await query.edit_message_text(
      text="Choose a CQZone", reply_markup=reply_markup
  )
  return START_ROUTES

async def cqzone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """Return send the graph corresponding to the zone and returns
  `ConversationHandler.END` which tells the conversationHandler that the conversation is over.
  """
  query = update.callback_query
  zone = query.data
  await query.answer()
  await query.message.reply_photo(
    f'https://bsdworld.org/DXCC/cqzone/{zone}/latest.webp?{rid()}',
    caption=(f"Propagation for CQZone {zone}{SOURCE}")
  )
  await query.edit_message_reply_markup(reply_markup=None)
  return ConversationHandler.END


async def continent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """Send the graph corresponding to the continent and returns
  `ConversationHandler.END` witch tell the conversationHandler that the conversation is over.
  """
  labels = {
    'NA': "North America\n73 and good DXing",
    'EU': "Europa\n73 and good DXing",
  }
  query = update.callback_query
  con = query.data.lstrip('@')
  url = f'https://bsdworld.org/DXCC/continent/{con}/latest.webp?{rid()}'
  logging.info(url)
  await query.answer()
  await query.message.reply_photo(url, caption=f"{labels[con]}{SOURCE}")
  await query.edit_message_reply_markup(reply_markup=None)
  return ConversationHandler.END


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  """Send a message when the command /help is issued."""
  help = ["*Group commands:*\n"]
  commands = {k: v[1] for k, v in RESOURCES.items()}
  commands['/help'] = 'This message'
  commands['/bands'] = 'Propagation by band and continent'
  commands['/alerts'] = 'Solar activity alerts'

  for cmd, label in sorted(commands.items()):
    help.append(f"{cmd} : {label}")
  await update.message.reply_text("\n".join(help), parse_mode=ParseMode.MARKDOWN)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
  """Log the error and send a telegram message to notify the developer."""
  logger.error("Exception while handling an update:", exc_info=context.error)

  # traceback.format_exception returns the usual python message about an exception
  tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
  tb_string = "".join(tb_list)

  # Build the message with some markup and additional information about what happened.
  update_str = update.to_dict() if isinstance(update, Update) else str(update)
  message = (
    "An exception was raised while handling an update\n"
    f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
    "</pre>\n\n"
    f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
    f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
    f"<pre>{html.escape(tb_string)}</pre>"
  )
  # Send the message
  await context.bot.send_message(
    chat_id=Config.developer_id, text=message, parse_mode=ParseMode.HTML
  )


def main() -> None:
  """Run the bot."""
  load_config()
  # Create the Application and pass it your bot's token.
  application = Application.builder().token(Config.token).build()

  # The error handler
  application.add_error_handler(error_handler)

  conv_handler = ConversationHandler(
    entry_points=[
      CommandHandler("start", start),
      CommandHandler("band", bands),
      CommandHandler("bands", bands),
      CommandHandler("alerts", alerts),
    ],
    states={
      START_ROUTES: [
        CallbackQueryHandler(north_america, pattern="^NA$"),
        CallbackQueryHandler(europe, pattern="^EU$"),
        CallbackQueryHandler(continent, pattern="^@NA$"),
        CallbackQueryHandler(continent, pattern="^@EU$"),
        CallbackQueryHandler(cqzone, pattern="^\d+$"),
      ],
    },
    fallbacks=[
      CommandHandler("band", bands),
      CommandHandler("bands", bands),
    ],
  )

  # Add ConversationHandler to application that will be used for handling updates
  application.add_handler(conv_handler)
  for command in RESOURCES.keys():
    application.add_handler(CommandHandler(command.lstrip('/'), send_graph))
  application.add_handler(CommandHandler("help", help_handler))

  # Run the bot until the user presses Ctrl-C
  application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
