#!/usr/bin/env python
# pylint: disable=unused-argument

"""
Send /start to initiate the conversation.
"""

import html
import json
import logging
import os
import pathlib
import time
import traceback

from itertools import islice
from typing import Optional
from urllib.parse import urljoin

import aiofiles
import httpx
import yaml

from telegram import (
  InlineKeyboardButton,
  InlineKeyboardMarkup,
  Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
  Application,
  CallbackQueryHandler,
  CommandHandler,
  ContextTypes,
  ConversationHandler,
)

# Enable logging
logging.basicConfig(
  format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Stages
CONFIG_FILES = ("sunbot.conf", "~/.local/sunbot.conf", "/etc/sunbot.conf")
START_ROUTES, INFO = 1, 2
SOURCE = "\nMore information at https://bsdworld.org/"
NOAA_URL = 'https://services.swpc.noaa.gov/'

RESOURCES = {
  "/aindex": [
    "https://bsdworld.org/aindex.jpg",
    "The A index show the fluctuations in the magnetic field."
  ],
  "/dxcc": [
    "https://bsdworld.org/dxcc-week-stats.jpg",
    "Daily total number of spots for each continents."
  ],
  "/enlil": [
    "https://bsdworld.org/enlil.mp4",
    "WSA-Enlil Solar Wind Prediction."
  ],
  "/flux": [
    "https://bsdworld.org/flux.jpg",
    "Solar radio flux at 10.7 cm (2800 MHz) is an indicator of solar activity."
  ],
  "/forecast": [
    "https://bsdworld.org/kpi-forecast.jpg",
    "Recently observed and a three day forecast of space weather conditions."
  ],
  "/kpindex": [
    "https://bsdworld.org/kpindex.jpg",
    "Kp is an indicator of disturbances in the Earth's magnetic field."
  ],
  "/modes": [
    "https://bsdworld.org/modes.jpg",
    "Daily total activity per mode."
  ],
  "/muf": [
    "https://bsdworld.org/muf.mp4",
    "Show the maximum usable frequency."
  ],
  "/proton": [
    "https://bsdworld.org/proton_flux.jpg",
    "Proton Flux is the number of high-energy protons coming from the Sun."
  ],
  "/sunspot": [
    "https://bsdworld.org/ssn.jpg",
    "Daily index of sunspot activity."
  ],
  "/wind": [
    "https://bsdworld.org/solarwind.jpg",
    "Density, speed, and temperature of protons and electrons plasma."
  ],
  "/xray": [
    "https://bsdworld.org/xray_flux.jpg",
    "X-ray emissions from the Sun are primarily associated with solar flares."
  ],
}


class Config:
  """Holds configuration informations"""
  # pylint: disable=too-few-public-methods
  token: str = None
  developer_id: int | None = None


class Terms(dict):
  """Simgleton dictionary containing the terms definitions"""
  _instance = None

  def __new__(cls, *args, **kwargs):
    if cls._instance is None:
      cls._instance = super(Terms, cls).__new__(cls)
    return cls._instance

  def __init__(self):
    if self:
      return
    data_dir = os.path.dirname(__file__)
    data_path = os.path.join(data_dir, 'help.yaml')

    print(data_path)
    with open(data_path, 'r', encoding='utf-8') as fdi:
      data = yaml.safe_load(fdi)
    super().__init__({k.lower(): v for k, v in data.items()})

  def __getitem__(self, key):
    if isinstance(key, str):
      key = key.lower()
    return super().__getitem__(key)


def batched(iterable, batch_len):
  """This function is from the package more-itertools"""
  # batched('ABCDEFG', 3) --> ABC DEF G
  if batch_len < 1:
    raise ValueError('n must be at least one')
  _it = iter(iterable)
  while batch := tuple(islice(_it, batch_len)):
    yield batch


def load_config() -> None:
  """load token and developer_id from the config file"""
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
        logger.warning("config error: %s", line)


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


async def text_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  """Downlaod the forecast text file, format it and send it to the user"""
  url = urljoin(NOAA_URL, '/text/discussion.txt')
  cache_file = '/tmp/discussion.txt'
  await load_cache_file(url, cache_file, 3600*4)
  forecast = []
  flag = 0
  async with aiofiles.open(cache_file, mode='r', encoding="utf-8") as fdin:
    async for line in fdin:
      line = line.strip()
      if line.startswith('.Forecast'):
        flag = 1
        continue
      if flag and not line:
        break
      if flag:
        forecast.append(line)
  await update.message.reply_text(' '.join(forecast))


async def send_graph(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """Send the flux graph"""
  message = update.effective_message
  user = update.effective_user
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


async def alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  """download and send the NOAA alerts"""
  url = urljoin(NOAA_URL, "/text/wwv.txt")
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

  message = update.effective_message
  user = update.effective_user
  logger.info("User %s command %s", user.first_name, message.text)
  await update.message.reply_text('\n'.join(alert))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  """Send a message when the command /start is issued."""
  message = update.effective_message
  user = message.from_user
  response = (
    f"Hi {user.mention_markdown()} and welcome.",
    "Use '/help' to see the list of commands.",
    "SunFluxBot developped by [W6BSD](https://0x9900.com/)"
  )
  await update.message.reply_markdown('\n'.join(response))
  message = update.effective_message
  user = update.effective_user
  logger.info("User %s command %s", user.first_name, message.text)


async def bands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """Send message on `/bands`."""
  message = update.effective_message
  user = update.effective_user
  logger.info("User %s command %s", user.first_name, message.text)
  keyboard = [
    [
      InlineKeyboardButton("North America", callback_data=str("NA")),
      InlineKeyboardButton("Europe", callback_data=str("EU")),
    ]
  ]
  reply_markup = InlineKeyboardMarkup(keyboard)
  await update.message.reply_text("Propagation: Choose a continent", reply_markup=reply_markup)
  return START_ROUTES


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
  await query.edit_message_text(text="Choose a CQZone", reply_markup=reply_markup)
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
  await query.edit_message_text(text="Choose a CQZone", reply_markup=reply_markup)
  return START_ROUTES


async def info_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  """Show the information menu for the words definitions"""
  message = update.effective_message
  user = update.effective_user
  logger.info("User %s command %s", user.first_name, message.text)
  text = message.text.split()
  terms = Terms()
  if len(text) == 2:
    keyword = text[1]
    term_def = f'*Information about {keyword}:*\n' + terms.get(keyword, 'No definition found')
    await update.message.reply_text(text=term_def, parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END

  keyboard = []
  for keywords in batched(terms, 2):
    row = []
    for item in keywords:
      row.append(InlineKeyboardButton(item, callback_data=item))
    keyboard.append(row)
  reply_markup = InlineKeyboardMarkup(keyboard)
  await update.message.reply_text("Choose a keyword", reply_markup=reply_markup)
  return INFO


async def definition(update: Update, contex: ContextTypes.DEFAULT_TYPE) -> int:
  """Lookup the term definition and send a message"""
  query = update.callback_query
  keyword = query.data
  terms = Terms()
  await query.answer()
  word_def = f'*Information about {keyword}:*\n' + terms.get(keyword, 'not found')
  await query.edit_message_text(text=word_def, parse_mode=ParseMode.MARKDOWN)
  return ConversationHandler.END


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
  logger.info(url)
  await query.answer()
  await query.message.reply_photo(url, caption=f"{labels[con]}{SOURCE}")
  await query.edit_message_reply_markup(reply_markup=None)
  return ConversationHandler.END


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  """Send a message when the command /help is issued."""
  message = update.effective_message
  user = update.effective_user
  logger.info("User %s command %s", user.first_name, message.text)
  help_msg = ["*Group commands:*\n"]
  commands = {k: v[1] for k, v in RESOURCES.items()}
  commands['/help'] = 'This message.'
  commands['/bands'] = 'Propagation by band and continent.'
  commands['/alerts'] = 'Solar activity alerts.'
  commands['/forecast'] = 'Forecast Discussion.'
  commands['/info'] = 'Definition of certain terms.'

  for cmd, label in sorted(commands.items()):
    help_msg.append(f"{cmd} : {label}")
  await update.message.reply_text("\n".join(help_msg), parse_mode=ParseMode.MARKDOWN)


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


def main() -> int:
  """Run the bot."""
  try:
    load_config()
  except FileNotFoundError as err:
    logger.error(err)
    return os.EX_CONFIG

  # Create the Application and pass it your bot's token.
  application = Application.builder().token(Config.token).build()

  # The error handler
  application.add_error_handler(error_handler)

  conv_handler = ConversationHandler(
    entry_points=[
      CommandHandler("band", bands),
      CommandHandler("bands", bands),
      CommandHandler("info", info_menu),
    ],
    states={
      START_ROUTES: [
        CallbackQueryHandler(north_america, pattern=r"^NA$"),
        CallbackQueryHandler(europe, pattern=r"^EU$"),
        CallbackQueryHandler(continent, pattern=r"^@NA$"),
        CallbackQueryHandler(continent, pattern=r"^@EU$"),
        CallbackQueryHandler(cqzone, pattern=r"^\d+$"),
      ],
      INFO: [
        CallbackQueryHandler(definition, pattern=r"^\w+$"),
      ]
    },
    fallbacks=[
      CommandHandler("band", bands),
      CommandHandler("bands", bands),
    ],
  )

  # Add ConversationHandler to application that will be used for handling updates
  application.add_handler(conv_handler)

  # Add commands to the application
  application.add_handler(CommandHandler("alert", alerts))
  application.add_handler(CommandHandler("alerts", alerts))
  application.add_handler(CommandHandler("command", help_handler))
  application.add_handler(CommandHandler("commands", help_handler))
  application.add_handler(CommandHandler("help", help_handler))
  application.add_handler(CommandHandler("prediction", text_forecast))
  application.add_handler(CommandHandler("predictions", text_forecast))
  application.add_handler(CommandHandler("start", start))
  for command in RESOURCES:
    application.add_handler(CommandHandler(command.lstrip('/'), send_graph))

  # Run the bot until the user presses Ctrl-C
  application.run_polling(allowed_updates=Update.ALL_TYPES)
  return os.EX_OK


if __name__ == "__main__":
  main()
