import pyrogram

from VampireMusic import config, logger


class Bot(pyrogram.Client):
    def __init__(self):
        super().__init__(
            name="bot",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN,
            parse_mode=pyrogram.enums.ParseMode.HTML,
            max_concurrent_transmissions=7,
            link_preview_options=pyrogram.types.LinkPreviewOptions(is_disabled=True),
            in_memory=True,
        )
        self.owner = config.OWNER_ID
        self.logger = config.LOGGER_ID
        self.bl_users = pyrogram.filters.user()
        self.sudoers = pyrogram.filters.user(self.owner)

    async def boot(self):
        """
        Starts the bot and performs initial setup.

        Raises:
            SystemExit: If the bot fails to access the log group or is not an administrator in the logger group.
        """
        await super().start()
        self.id = self.me.id
        from config import Config
        self.name = Config().BOT_NAME
        self.username = self.me.username
        self.mention = self.me.mention

        # Set bot commands for suggestions
        commands = [
            pyrogram.types.BotCommand("start", "Start the bot"),
            pyrogram.types.BotCommand("help", "Get help"),
            pyrogram.types.BotCommand("play", "Play a song"),
            pyrogram.types.BotCommand("vplay", "Play a video"),
            pyrogram.types.BotCommand("pause", "Pause current song"),
            pyrogram.types.BotCommand("resume", "Resume paused song"),
            pyrogram.types.BotCommand("skip", "Skip to next song"),
            pyrogram.types.BotCommand("end", "End playback"),
            pyrogram.types.BotCommand("queue", "Show current queue"),
            pyrogram.types.BotCommand("shuffle", "Shuffle queue"),
            pyrogram.types.BotCommand("loop", "Loop playback"),
            pyrogram.types.BotCommand("seek", "Seek to position"),
            pyrogram.types.BotCommand("speed", "Change playback speed"),
            pyrogram.types.BotCommand("ping", "Check bot ping"),
            pyrogram.types.BotCommand("stats", "Show bot stats"),
            pyrogram.types.BotCommand("auth", "Authorize user"),
            pyrogram.types.BotCommand("unauth", "Unauthorize user"),
            pyrogram.types.BotCommand("gcast", "Global broadcast"),
            pyrogram.types.BotCommand("tagall", "Tag all members (3 per message)"),
            pyrogram.types.BotCommand("tag", "Tag all members (1 per message)"),
            pyrogram.types.BotCommand("atag", "Tag all admins (1 per message)"),
            pyrogram.types.BotCommand("stag", "Stop tagging"),
            pyrogram.types.BotCommand("mute", "Mute a member"),
            pyrogram.types.BotCommand("unmute", "Unmute a member"),
            pyrogram.types.BotCommand("ban", "Ban a member"),
            pyrogram.types.BotCommand("unban", "Unban a member"),
            pyrogram.types.BotCommand("promote", "Promote a member to admin"),
            pyrogram.types.BotCommand("demote", "Demote an admin"),
        ]
        try:
            await self.set_bot_commands(commands)
        except Exception as e:
            logger.warning(f"Failed to set bot commands: {e}")
            
        try:
            await self.send_message(self.logger, "Bot Started")
            get = await self.get_chat_member(self.logger, self.id)
            if get.status != pyrogram.enums.ChatMemberStatus.ADMINISTRATOR:
                logger.warning("Please promote the bot as an admin in logger group.")
        except Exception as ex:
            logger.warning(f"Bot has failed to access the log group: {self.logger}\nReason: {ex}")
            
        logger.info(f"Bot started as @{self.username}")

    async def exit(self):
        """
        Asynchronously stops the bot.
        """
        await super().stop()
        logger.info("Bot stopped.")
