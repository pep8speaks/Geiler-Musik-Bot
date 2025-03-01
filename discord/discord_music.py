from asyncio import Queue
from discord.ext import commands
import discord
import random
import asyncio
import spotify
import youtube
import mongo
import time
import string
import logging_manager
import lastfm
import collections
import aiohttp
import re
from variable_store import VariableStore


class DiscordBot(commands.Cog):
    def __init__(self, bot):
        self.dictionary = {}
        self.bot = bot
        self.log = logging_manager.LoggingManager()
        self.spotify = spotify.Spotify()
        self.youtube = youtube.Youtube()
        self.lastfm = lastfm.LastFM()
        self.mongo = mongo.Mongo()
        bot.remove_command("help")
        self.log.debug("[Startup]: Initializing Music Module . . .")

        def generate_key(length):
            letters = string.ascii_letters
            response = ""
            for a in range(0, length):
                response += random.choice(letters)
            return response

        restart_key = generate_key(64)
        asyncio.run_coroutine_threadsafe(self.mongo.set_restart_key(restart_key), self.bot.loop)

        if not discord.opus.is_loaded():
            discord.opus.load_opus("/usr/lib/libopus.so")

    async def clear_presence(self, ctx):
        if self.dictionary[ctx.guild.id]["now_playing_message"] is not None:
            await self.dictionary[ctx.guild.id]["now_playing_message"].delete()
            self.dictionary[ctx.guild.id]["now_playing_message"] = None
        await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=".help"))

    async def send_error_message(self, ctx, message):
        embed = discord.Embed(title="Error", description=message)
        await ctx.send(embed=embed)

    async def empty_channel(self, ctx):
        if len(self.dictionary[ctx.guild.id]["voice_channel"].members) == 1:
            self.dictionary[ctx.guild.id]["new_song_queue"] = Queue()
            await self.dictionary[ctx.guild.id]["voice_client"].disconnect()
            embed = discord.Embed(
                title="I've left the channel, because it was empty.", color=0x00FFCC, url="https://d.chulte.de"
            )
            await ctx.send(embed=embed)

    async def preload_song(self, ctx):
        if self.dictionary[ctx.guild.id]["new_song_queue"].qsize() > 0:
            i = 0
            for item in self.dictionary[ctx.guild.id]["new_song_queue"]._queue:
                if "stream" not in item:
                    if "link" in item:
                        youtube_dict = await self.youtube.youtube_url(item["link"])
                        youtube_dict["user"] = item["user"]
                    else:
                        if "title" in item:
                            youtube_dict = await self.youtube.youtube_term(item["title"])
                        else:
                            youtube_dict = await self.youtube.youtube_term(item["term"])
                        youtube_dict["user"] = item["user"]
                    self.dictionary[ctx.guild.id]["new_song_queue"]._queue[i] = youtube_dict
                    break
                i += 1

    def song_conclusion(self, ctx):
        self.dictionary[ctx.guild.id]["now_playing_song"] = None
        function = asyncio.run_coroutine_threadsafe(self.clear_presence(ctx), self.bot.loop)
        try:
            function.result()
        except Exception as e:
            self.log.error(logging_manager.debug_info(str(e)))
        function = asyncio.run_coroutine_threadsafe(self.empty_channel(ctx), self.bot.loop)
        try:
            function.result()
        except Exception as e:
            self.log.error(logging_manager.debug_info(str(e)))
        function = asyncio.run_coroutine_threadsafe(self.pre_player(ctx), self.bot.loop)
        try:
            function.result()
        except Exception as e:
            self.log.error(logging_manager.debug_info(str(e)))

    async def messaging(self, message, ctx, full, empty):
        try:
            if self.dictionary[ctx.guild.id]["now_playing_song"]["is_paused"] is False:
                now_time = (
                    int(time.time())
                    - self.dictionary[ctx.guild.id]["now_playing_song"]["start_time"]
                    - self.dictionary[ctx.guild.id]["now_playing_song"]["pause_duration"]
                )

                if ":" in str(self.dictionary[ctx.guild.id]["now_playing_song"]["duration"]):
                    finish_second = (
                        int(str(self.dictionary[ctx.guild.id]["now_playing_song"]["duration"]).split(":")[0]) * 3600
                        + int(str(self.dictionary[ctx.guild.id]["now_playing_song"]["duration"]).split(":")[1]) * 60
                        + int(str(self.dictionary[ctx.guild.id]["now_playing_song"]["duration"]).split(":")[2])
                    )
                    description = (
                        time.strftime("%H:%M:%S", time.gmtime(now_time))
                        + " / "
                        + str(self.dictionary[ctx.guild.id]["now_playing_song"]["duration"])
                    )
                else:
                    finish_second = int(self.dictionary[ctx.guild.id]["now_playing_song"]["duration"])
                    description = (
                        time.strftime("%H:%M:%S", time.gmtime(now_time))
                        + " / "
                        + time.strftime(
                            "%H:%M:%S", time.gmtime(self.dictionary[ctx.guild.id]["now_playing_song"]["duration"])
                        )
                    )

                percentage = int((now_time / finish_second) * 100)

                if percentage > 100:
                    percentage = 100
                count = percentage / 4
                hashes = ""
                while count > 0:
                    hashes += full
                    count -= 1
                while len(hashes) < 25:
                    hashes += empty
                hashes += " " + str(percentage) + "%"
                if self.dictionary[ctx.guild.id]["now_playing_song"]["title"] == "_":
                    title = self.dictionary[ctx.guild.id]["now_playing_song"]["term"]
                else:
                    title = self.dictionary[ctx.guild.id]["now_playing_song"]["title"]

                embed2 = discord.Embed(
                    title=title, color=0x00FFCC, url=self.dictionary[ctx.guild.id]["now_playing_song"]["link"]
                )
                embed2.set_author(name="Currently Playing:")
                embed2.add_field(name=hashes, value=description)
                try:
                    if "image_url" in self.dictionary[ctx.guild.id]["now_playing_song"]:
                        if self.dictionary[ctx.guild.id]["now_playing_song"]["image_url"] is not None:
                            if self.dictionary[ctx.guild.id]["now_playing_song"]["image_url"] != "":
                                embed2.set_thumbnail(url=self.dictionary[ctx.guild.id]["now_playing_song"]["image_url"])
                            # self.dictionary[ctx.guild.id]['now_playing_song']['image_url'] = ""
                except Exception as e:
                    self.log.error(logging_manager.debug_info(str(e)))
                try:
                    await message.edit(embed=embed2)
                except discord.NotFound:
                    return
                if now_time >= finish_second:
                    return
        except TypeError:
            return
        await asyncio.sleep(2)  # Image Flicker Reduction
        await self.messaging(message, ctx, full, empty)

    async def player(self, ctx, small_dict):
        x = 0
        # while x in range(0, 2, 1):

        if small_dict["error"] is True:
            error_message = "An error has occured."
            if "reason" in small_dict:
                error_message = small_dict["reason"]
            await self.send_error_message(ctx, error_message)
            return

        try:
            self.dictionary[ctx.guild.id]["now_playing_song"] = small_dict
            self.dictionary[ctx.guild.id]["now_playing_song"]["start_time"] = int(time.time())
            self.dictionary[ctx.guild.id]["now_playing_song"]["is_paused"] = False
            self.dictionary[ctx.guild.id]["now_playing_song"]["pause_duration"] = 0
            if "title" in small_dict:
                await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing,
                                                                         name=small_dict["title"]))
            volume = await self.mongo.get_volume(ctx.guild.id)
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    small_dict["stream"],
                    executable="ffmpeg",
                    before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                ),
                volume=volume,
            )
            self.dictionary[ctx.guild.id]["voice_client"].play(
                source, after=lambda _: self.song_conclusion(ctx)
            )  # do after
            full, empty = await self.mongo.get_chars(ctx.guild.id)
            asyncio.ensure_future(
                self.messaging(self.dictionary[ctx.guild.id]["now_playing_message"], ctx, full, empty)
            )
        except Exception as e:
            print(e)
            x += 1
            pass

    async def preload_album_art(self, ctx):
        try:
            song_title = self.dictionary[ctx.guild.id]["now_playing_song"]["title"]
            search_term = self.dictionary[ctx.guild.id]["now_playing_song"]["term"]
            if song_title == "_":
                self.dictionary[ctx.guild.id]["now_playing_song"]["image_url"] = await self.lastfm.get_album_art(
                    search_term, search_term
                )
            else:
                self.dictionary[ctx.guild.id]["now_playing_song"]["image_url"] = await self.lastfm.get_album_art(
                    song_title, search_term
                )
        except (IndexError, TypeError, KeyError, NameError) as e:
            self.log.warning(logging_manager.debug_info(str(e)))

    async def pre_player(self, ctx):
        if self.dictionary[ctx.guild.id]["new_song_queue"].qsize() > 0:
            small_dict = await self.dictionary[ctx.guild.id]["new_song_queue"].get()
            embed = discord.Embed(title="🔁 Loading ... 🔁", color=0x00FFCC, url="https://d.chulte.de")
            self.dictionary[ctx.guild.id]["now_playing_message"] = await ctx.send(embed=embed)
            if "stream" not in small_dict:
                if "link" in small_dict:
                    # url
                    youtube_dict = await self.youtube.youtube_url(small_dict["link"])
                else:
                    if "title" not in small_dict:
                        self.log.warning(small_dict)
                    # term
                    youtube_dict = await self.youtube.youtube_term(small_dict["title"])
                    # youtube_dict = await self.youtube_t.youtube_term(small_dict['title'])
                youtube_dict["user"] = small_dict["user"]
                await self.player(ctx, youtube_dict)
            else:
                await self.player(ctx, small_dict)

            asyncio.ensure_future(self.preload_album_art(ctx=ctx))
            asyncio.ensure_future(self.preload_song(ctx=ctx))

    async def add_to_queue(self, url, ctx, first_index_push=False, playskip=False):
        if playskip:
            self.dictionary[ctx.guild.id]["new_song_queue"] = Queue()
        yt_pattern = VariableStore.youtube_url_pattern
        spotify_pattern = VariableStore.spotify_url_pattern

        small_dict = dict()
        small_dict["user"] = ctx.message.author

        small_dicts = []

        _multiple = False

        if re.match(yt_pattern, url) is not None:
            if "watch?" in url.lower() or "youtu.be" in url.lower():
                small_dict["link"] = url
                _multiple = False
            elif "playlist" in url:
                song_list = await self.youtube.youtube_playlist(url)
                for track in song_list:
                    track["user"] = ctx.message.author
                    small_dicts.append(track)
                _multiple = True
        elif re.match(spotify_pattern, url) is not None:
            if "playlist" in url:
                song_list = await self.spotify.spotify_playlist(url)
                if len(song_list) == 0:
                    embed = discord.Embed(
                        title="**There was an error pulling the Spotify Playlist, 0 Songs were added.**",
                        url="https://github.com/tooxo/Geiler-Musik-Bot/issues",
                        color=0x00FFCC,
                    )
                    await ctx.send(embed=embed)
                    return
                for track in song_list:
                    song = dict(small_dict)
                    song["title"] = track
                    small_dicts.append(song)
                _multiple = True
            elif "track" in url:
                track = await self.spotify.spotify_track(url)
                small_dict["title"] = track
                _multiple = False
            elif "album" in url:
                song_list = await self.spotify.spotify_album(url)
                for track in song_list:
                    song = dict(small_dict)
                    song["title"] = track
                    small_dicts.append(song)
                _multiple = True
            elif "artist" in url:
                song_list = await self.spotify.spotify_artist(url)
                for track in song_list:
                    song = dict(small_dict)
                    song["title"] = track
                    small_dicts.append(song)
                _multiple = True

        else:
            small_dict["title"] = url
            _multiple = False

        if _multiple:
            for song in small_dicts:
                self.dictionary[ctx.guild.id]["new_song_queue"].put_nowait(song)
            embed = discord.Embed(
                title=":asterisk: Added " + str(len(small_dicts)) + " Tracks to Queue. :asterisk:",
                url="https://d.chulte.de",
                color=0x00FFCC,
            )
            await ctx.send(embed=embed)
        else:
            if first_index_push:
                self.dictionary[ctx.guild.id]["new_song_queue"]._queue.appendleft(small_dict)
            else:
                self.dictionary[ctx.guild.id]["new_song_queue"].put_nowait(small_dict)
            title = ""
            if "title" in small_dict:
                title = small_dict["title"]
            else:
                try:
                    title = small_dict["link"]
                except KeyError:
                    pass
            embed = discord.Embed(
                title=":asterisk: Added **" + title + "** to Queue.", url="https://d.chulte.de", color=0x00FFCC
            )
            if self.dictionary[ctx.guild.id]["voice_client"].is_playing():
                await ctx.send(embed=embed)

        if playskip:
            await self.dictionary[ctx.guild.id]["voice_client"].stop()
        if not self.dictionary[ctx.guild.id]["voice_client"].is_playing():
            await self.pre_player(ctx)
        await self.preload_song(ctx)

    async def join_check(self, ctx, url):
        if url is None:
            embed = discord.Embed(
                title="You need to enter something to play.", url="https://d.chulte.de", color=0x00FFCC
            )
            await ctx.send(embed=embed)
            return False
        self.dictionary = self.dictionary
        try:
            if self.dictionary[ctx.guild.id]["voice_channel"] is None:
                self.dictionary[ctx.guild.id]["voice_channel"] = ctx.author.voice.channel
        except Exception as e:
            self.log.warning(logging_manager.debug_info("channel_join " + str(e)))
            embed = discord.Embed(title="You need to be in a channel.", color=0x00FFCC, url="https://d.chulte.de")
            self.dictionary[ctx.guild.id]["voice_channel"] = None
            await ctx.send(embed=embed)
            return False
        try:
            if ctx.me.voice.channel != ctx.author.voice.channel:
                embed = discord.Embed(
                    title="You need to be in the same channel as the bot.", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)
                return False
        except AttributeError:
            pass
        return True

    async def join_channel(self, ctx):
        if self.dictionary[ctx.guild.id]["voice_client"] is None:
            try:
                if (
                    ctx.author.voice.channel.user_limit <= len(ctx.author.voice.channel.members)
                    and ctx.author.voice.channel.user_limit != 0
                ):
                    if ctx.guild.me.guild_permissions.administrator is True:
                        self.dictionary[ctx.guild.id]["voice_client"] = await ctx.author.voice.channel.connect(
                            timeout=60, reconnect=True
                        )
                    else:
                        embed = discord.Embed(
                            title="Error while joining your channel. :frowning: (1)",
                            url="https://d.chulte.de",
                            color=0x00FFCC,
                        )
                        await ctx.send(embed=embed)
                        return False
                else:
                    self.dictionary[ctx.guild.id]["voice_client"] = await ctx.author.voice.channel.connect(
                        timeout=60, reconnect=True
                    )
            except (TimeoutError, discord.HTTPException, discord.ClientException, discord.DiscordException) as e:
                self.log.warning(logging_manager.debug_info("channel_join " + str(e)))
                self.dictionary[ctx.guild.id]["voice_channel"] = None
                embed = discord.Embed(
                    title="Error while joining your channel. :frowning: (2)", url="https://d.chulte.de", color=0x00FFCC
                )
                await ctx.send(embed=embed)
                return False
        return True

    @commands.command(aliases=["p"])
    async def play(self, ctx, *, url: str = None):
        if not await self.join_check(ctx, url):
            return
        if not await self.join_channel(ctx=ctx):
            return

        youtube_pattern = VariableStore.youtube_url_pattern
        spotify_pattern = VariableStore.spotify_url_pattern

        if (
            re.match(youtube_pattern, url) is not None
            or re.match(spotify_pattern, url) is not None
            or url.lower() == "charts"
        ):
            await self.add_to_queue(url, ctx)
        else:
            url_pattern = VariableStore.url_pattern
            if re.match(url_pattern, url) is not None:
                embed = discord.Embed(
                    title="This is not a valid/supported url.", url="https://d.chulte.de", color=0x00FFCC
                )
                await ctx.send(embed=embed)
                return
            else:
                await self.add_to_queue(url, ctx)

    @commands.command(aliases=["pn"])
    async def playnext(self, ctx, *, url: str = None):
        if not await self.join_check(ctx, url):
            return
        if not await self.join_channel(ctx=ctx):
            return

        youtube_pattern = VariableStore.youtube_url_pattern
        spotify_pattern = VariableStore.spotify_url_pattern

        if (
            re.match(youtube_pattern, url) is not None
            or re.match(spotify_pattern, url) is not None
            or url.lower() == "charts"
        ):
            await self.add_to_queue(url, ctx, first_index_push=True)
        else:

            if re.match(VariableStore.url_pattern, url) is not None:
                embed = discord.Embed(
                    title="This is not a valid/supported url.", url="https://d.chulte.de", color=0x00FFCC
                )
                await ctx.send(embed=embed)
                return
            else:
                await self.add_to_queue(url, ctx, first_index_push=True)

    @commands.command(aliases=["ps"])
    async def playskip(self, ctx, *, url: str = None):
        if not await self.join_check(ctx, url):
            return
        if not await self.join_channel(ctx=ctx):
            return

        youtube_pattern = VariableStore.youtube_url_pattern
        spotify_pattern = VariableStore.spotify_url_pattern

        if (
            re.match(youtube_pattern, url) is not None
            or re.match(spotify_pattern, url) is not None
            or url.lower() == "charts"
        ):
            await self.add_to_queue(url, ctx, playskip=True)
        else:
            if re.match(VariableStore.url_pattern, url) is not None:
                embed = discord.Embed(
                    title="This is not a valid/supported url.", url="https://d.chulte.de", color=0x00FFCC
                )
                await ctx.send(embed=embed)
                return
            else:
                await self.add_to_queue(url, ctx, playskip=True)

    async def cog_before_invoke(self, ctx):
        if ctx.guild.id not in self.dictionary:
            self.dictionary[ctx.guild.id] = dict()
        if "new_song_queue" not in self.dictionary[ctx.guild.id]:
            self.dictionary[ctx.guild.id]["new_song_queue"] = Queue()
        if "voice_client" not in self.dictionary[ctx.guild.id]:
            self.dictionary[ctx.guild.id]["voice_client"] = None
        if "voice_channel" not in self.dictionary[ctx.guild.id]:
            self.dictionary[ctx.guild.id]["voice_channel"] = None
        if "now_playing_song" not in self.dictionary[ctx.guild.id]:
            self.dictionary[ctx.guild.id]["now_playing_song"] = None
        if self.dictionary[ctx.guild.id]["voice_channel"] is None:
            if ctx.me.voice is not None:
                if hasattr(ctx.me.voice, "channel"):
                    print("RECONNECTING")
                    self.dictionary[ctx.guild.id]["voice_channel"] = ctx.me.voice.channel
                    t = await ctx.me.voice.channel.connect(timeout=5, reconnect=False)
                    await t.disconnect()
                    self.dictionary[ctx.guild.id]["voice_client"] = await ctx.me.voice.channel.connect(
                        timeout=60, reconnect=True
                    )

    @commands.command(aliases=["q"])
    async def queue(self, ctx):
        self.dictionary = self.dictionary
        song_queue = self.dictionary[ctx.guild.id]["new_song_queue"]._queue
        np_song = self.dictionary[ctx.guild.id]["now_playing_song"]
        embed = discord.Embed(color=0x00FFCC, url="https://d.chulte.de")
        if np_song is not None:
            embed.add_field(name="**Currently Playing...**", value="`" + np_song["title"] + "`\n", inline=False)
        else:
            embed.add_field(name="**Currently Playing...**", value="Nothing.\n", inline=False)
        if len(song_queue) > 0:
            numbers = [":one:", ":two:", ":three:", ":four:", ":five:", ":six:", ":seven:", ":eight:", ":nine:"]

            numbers = ["`(1)`", "`(2)`", "`(3)`", "`(4)`", "`(5)`", "`(6)`", "`(7)`", "`(8)`", "`(9)`"]

            queue = ""
            for x in range(0, 9):
                try:
                    if "title" in song_queue[x]:
                        queue = queue + numbers[x] + " `" + song_queue[x]["title"] + "`\n"
                    elif "link" in song_queue[x]:
                        queue = queue + numbers[x] + " `" + song_queue[x]["link"] + "`\n"
                    else:
                        break
                except:
                    break
            if (len(song_queue) - 9) > 0:
                queue = queue + "`(+)` `" + str(len(song_queue) - 9) + " Tracks...`"
            embed.add_field(name="**Coming up:**", value=queue, inline=False)
        else:
            embed.add_field(name="**Coming up:**", value="Nothing in Queue. Use .play to add something.", inline=False)

        await ctx.send(embed=embed)

    @commands.command()
    async def rename(self, ctx, *, name: str):
        try:
            if ctx.guild.me.guild_permissions.administrator is False:
                embed = discord.Embed(
                    title="You need to be an Administrator to execute this action.",
                    color=0x00FFCC,
                    url="https://d.chulte.de",
                )
                await ctx.send(embed=embed)
                return
        except AttributeError as ae:
            self.log.error(logging_manager.debug_info("AttributeError " + str(ae)))
        try:
            if len(name) > 32:
                embed = discord.Embed(
                    title="Name too long. 32 chars is the limit.", url="https://d.chulte.de", color=0x00FFCC
                )
                await ctx.send(embed=embed)
            me = ctx.guild.me
            await me.edit(nick=name)
            embed = discord.Embed(
                title="Rename to **" + name + "** successful.", url="https://d.chulte.de", color=0x00FFCC
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = discord.Embed(title="An Error occurred: " + str(e), url="https://d.chulte.de", color=0x00FFCC)
            await ctx.send(embed=embed)

    @commands.command(aliases=["v"])
    async def volume(self, ctx, volume=None):
        try:
            if ctx.me.voice.channel != ctx.author.voice.channel:
                embed = discord.Embed(
                    title="You need to be in the same channel as the bot.", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        try:
            if not hasattr(ctx.author.voice, "channel"):
                embed = discord.Embed(title="You need to be in a channel.", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        if self.dictionary[ctx.guild.id]["voice_channel"] is None:
            embed = discord.Embed(title="The bot isn't connected.", color=0x00FFCC, url="https://d.chulte.de")
            await ctx.send(embed=embed)
            return
        current_volume = await self.mongo.get_volume(ctx.guild.id)
        if volume is None:
            embed = discord.Embed(
                title="The current volume is: " + str(current_volume) + ". It only updates on song changes, so beware.",
                color=0x00FFCC,
                url="https://d.chulte.de",
            )
            await ctx.send(embed=embed)
            return
        try:
            var = float(volume)
        except ValueError as e:
            embed = discord.Embed(title="You need to enter a number.", color=0x00FFCC, url="https://d.chulte.de")
            await ctx.send(embed=embed)
            return
        if var < 0 or var > 2:
            embed = discord.Embed(
                title="The number needs to be between 0.0 and 2.0.", color=0x00FFCC, url="https://d.chulte.de"
            )
            await ctx.send(embed=embed)
            return
        await self.mongo.set_volume(ctx.guild.id, var)
        embed = discord.Embed(title="The Volume was set to: " + str(var), color=0x00FFCC, url="https://d.chulte.de")
        await ctx.send(embed=embed)

    @commands.command()
    async def info(self, ctx):
        self.dictionary = self.dictionary
        if self.dictionary[ctx.guild.id]["now_playing_song"] is None:
            embed = discord.Embed(
                title="Information",
                description="Nothing is playing right now.",
                color=0x00FFCC,
                url="https://d.chulte.de",
            )
            if "image_url" in self.dictionary[ctx.guild.id]["now_playing_song"]:
                if self.dictionary[ctx]["now_playing_song"]["image_url"] is not "":
                    embed.set_thumbnail(url=self.dictionary[ctx.guild.id]["now_playing_song"]["image_url"])
            await ctx.send(embed=embed)
            return
        try:
            embed = discord.Embed(
                title="Information",
                description="Name: "
                + str(self.dictionary[ctx.guild.id]["now_playing_song"]["title"])
                + "\nStreamed from: "
                + str(self.dictionary[ctx.guild.id]["now_playing_song"]["link"])
                + "\nDuration: "
                + str(self.dictionary[ctx.guild.id]["now_playing_song"]["duration"])
                + "\nRequested by: <@!"
                + str(self.dictionary[ctx.guild.id]["now_playing_song"]["user"].id)
                + ">\nLoaded in: "
                + str(round(self.dictionary[ctx.guild.id]["now_playing_song"]["loadtime"], 2))
                + " sec."
                + "\nSearched Term: "
                + str(self.dictionary[ctx.guild.id]["now_playing_song"]["term"]),
                color=0x00FFCC,
                url="https://d.chulte.de",
            )
            await ctx.send(embed=embed)
        except (KeyError, TypeError) as e:
            self.log.warning(logging_manager.debug_info(str(e)))
            embed = discord.Embed(
                title="Error",
                description="An error occurred while checking info.",
                url="https://d.chulte.de",
                color=0x00FFCC,
            )
            await ctx.send(embed=embed)

    @commands.command(aliases=["exit"])
    async def quit(self, ctx):
        try:
            if ctx.me.voice.channel != ctx.author.voice.channel:
                embed = discord.Embed(
                    title="You need to be in the same channel as the bot.", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        try:
            if not hasattr(ctx.author.voice, "channel"):
                embed = discord.Embed(title="You need to be in a channel.", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        try:
            if self.dictionary[ctx.guild.id]["voice_channel"] is None:
                embed = discord.Embed(title="The bot isn't connected.", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed)
                return
            if self.dictionary[ctx.guild.id]["voice_client"] is not None:
                self.dictionary[ctx.guild.id]["now_playing_song"] = None
                self.dictionary[ctx.guild.id]["new_song_queue"] = Queue()
                await self.clear_presence(ctx)
                await self.dictionary[ctx.guild.id]["voice_client"].disconnect()
                self.dictionary[ctx.guild.id]["voice_client"] = None
                embed = discord.Embed(title="Goodbye! :wave:", url="https://d.chulte.de", color=0x00FFCC)
                await ctx.send(embed=embed)
            else:
                embed = discord.Embed(
                    title="I need to be in a channel to leave! :thinking:", url="https://d.chulte.de", color=0x00FFCC
                )
                await ctx.send(embed=embed)
        except Exception as e:
            print(e)

    @commands.command(aliases=["empty"])
    async def clear(self, ctx):
        try:
            if ctx.me.voice.channel != ctx.author.voice.channel:
                embed = discord.Embed(
                    title="You need to be in the same channel as the bot.", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        try:
            if not hasattr(ctx.author.voice, "channel"):
                embed = discord.Embed(title="You need to be in a channel.", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        if self.dictionary[ctx.guild.id]["voice_channel"] is None:
            embed = discord.Embed(title="The bot isn't connected.", color=0x00FFCC, url="https://d.chulte.de")
            await ctx.send(embed=embed)
            return
        if self.dictionary[ctx.guild.id]["new_song_queue"].qsize() is not 0:
            self.dictionary[ctx.guild.id]["new_song_queue"] = Queue()
            embed = discord.Embed(title="Cleared the Queue. :cloud:", color=0x00FFCC, url="https://d.chulte.de")
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="The Playlist was already empty! :cloud:", color=0x00FFCC, url="https://d.chulte.de"
            )
            await ctx.send(embed=embed)

    @commands.command(aliases=["mixer"])
    async def shuffle(self, ctx):
        try:
            if ctx.me.voice.channel != ctx.author.voice.channel:
                embed = discord.Embed(
                    title="You need to be in the same channel as the bot.", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        try:
            if not hasattr(ctx.author.voice, "channel"):
                embed = discord.Embed(title="You need to be in a channel.", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        if self.dictionary[ctx.guild.id]["voice_channel"] is None:
            embed = discord.Embed(title="The bot isn't connected.", color=0x00FFCC, url="https://d.chulte.de")
            await ctx.send(embed=embed)
            return
        if self.dictionary[ctx.guild.id]["new_song_queue"].qsize() > 0:
            random.shuffle(self.dictionary[ctx.guild.id]["new_song_queue"]._queue)
            embed = discord.Embed(
                title="Shuffled! :twisted_rightwards_arrows:", color=0x00FFCC, url="https://d.chulte.de"
            )
            await ctx.send(embed=embed)
            await self.preload_song(ctx)

    @commands.command(aliases=["yeehee"])
    async def stop(self, ctx):
        try:
            if ctx.me.voice.channel != ctx.author.voice.channel:
                embed = discord.Embed(
                    title="You need to be in the same channel as the bot.", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        try:
            if not hasattr(ctx.author.voice, "channel"):
                embed = discord.Embed(title="You need to be in a channel.", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        if self.dictionary[ctx.guild.id]["voice_channel"] is None:
            embed = discord.Embed(title="The bot isn't connected.", color=0x00FFCC, url="https://d.chulte.de")
            await ctx.send(embed=embed)
            return
        self.dictionary = self.dictionary
        if self.dictionary[ctx.guild.id]["voice_client"] is not None:
            self.dictionary[ctx.guild.id]["new_song_queue"] = Queue()
            self.dictionary[ctx.guild.id]["now_playing_song"] = None
            self.dictionary[ctx.guild.id]["voice_client"].stop()
            link = await self.youtube.youtube_url("https://www.youtube.com/watch?v=siLkbdVxntU")
            source = discord.FFmpegPCMAudio(
                link["stream"],
                executable="ffmpeg",
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            )
            self.dictionary[ctx.guild.id]["voice_client"].play(source)
            if (
                self.dictionary[ctx.guild.id]["voice_client"] is not None
                and self.dictionary[ctx.guild.id]["voice_client"].is_playing()
            ):
                embed = discord.Embed(title="Music Stopped! 🛑", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title=":thinking: The Bot isn't connected. :thinking:", color=0x00FFCC, url="https://d.chulte.de"
            )
            await ctx.send(embed=embed)

    @commands.command(aliases=[])
    async def chars(self, ctx, first=None, last=None):
        if first is None:
            full, empty = await self.mongo.get_chars(ctx.guild.id)
            embed = discord.Embed(
                title="You are currently using **" + full + "** for 'full' and **" + empty + "** for 'empty'",
                color=0x00FFCC,
            )
            embed.add_field(
                name="Syntax to add:",
                value=".chars <full> <empty> \n" "Useful Website: https://changaco.oy.lc/unicode-progress-bars/",
            )
            await ctx.send(embed=embed)
            return
        elif first == "reset" and last is None:
            await self.mongo.set_chars(ctx.guild.id, "█", "░")
            embed = discord.Embed(title="Characters reset to: Full: **█** and Empty: **░**", color=0x00FFCC)
            await ctx.send(embed=embed)
        elif last is None:
            embed = discord.Embed(
                title="You need to provide 2 Unicode Characters separated with a blank space.", color=0x00FFCC
            )
            await ctx.send(embed=embed)
            return
        if len(first) > 1 or len(last) > 1:
            embed = discord.Embed(title="The characters have a maximal length of 1.", color=0x00FFCC)
            await ctx.send(embed=embed)
            return
        await self.mongo.set_chars(ctx.guild.id, first, last)
        embed = discord.Embed(
            title="The characters got updated! Full: **" + first + "**, Empty: **" + last + "**", color=0x00FFCC
        )
        await ctx.send(embed=embed)

    @commands.command(aliases=["halteein"])
    async def pause(self, ctx):
        try:
            if ctx.me.voice.channel != ctx.author.voice.channel:
                embed = discord.Embed(
                    title="You need to be in the same channel as the bot.", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        try:
            if not hasattr(ctx.author.voice, "channel"):
                embed = discord.Embed(title="You need to be in a channel.", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        if self.dictionary[ctx.guild.id]["voice_channel"] is None:
            embed = discord.Embed(title="The bot isn't connected.", color=0x00FFCC, url="https://d.chulte.de")
            await ctx.send(embed=embed)
            return
        self.dictionary = self.dictionary
        if self.dictionary[ctx.guild.id]["now_playing_song"]["is_paused"] is True:
            embed = discord.Embed(title="Already Paused.", color=0x00FFCC, url="https://d.chulte.de")
            await ctx.send(embed=embed)
        if self.dictionary[ctx.guild.id]["voice_client"] is not None:
            try:
                self.dictionary[ctx.guild.id]["voice_client"].pause()
                embed = discord.Embed(title="Paused! ⏸", color=0x00FFCC, url="https://d.chulte.de")
                message = await ctx.send(embed=embed)
                self.dictionary[ctx.guild.id]["now_playing_song"]["pause_time"] = int(time.time())
                self.dictionary[ctx.guild.id]["now_playing_song"]["is_paused"] = True
                await asyncio.sleep(5)
                await message.delete()
                await ctx.message.delete()
            except Exception as e:
                self.log.error(logging_manager.debug_info(str(e)))
                embed = discord.Embed(
                    title=":thinking: Nothing is playing... :thinking:", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)

    @commands.command(aliases=["next", "müll", "s"])
    async def skip(self, ctx, count="1"):
        try:
            if ctx.me.voice.channel != ctx.author.voice.channel:
                embed = discord.Embed(
                    title="You need to be in the same channel as the bot.", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        try:
            count = int(count)
        except ValueError:
            embed = discord.Embed(title="Please provide a valid number.", url="https://d.chulte.de", color=0x00FFCC)
            await ctx.send(embed=embed)
            return
        self.dictionary = self.dictionary
        if self.dictionary[ctx.guild.id]["voice_client"] is not None:
            if self.dictionary[ctx.guild.id]["now_playing_song"] is not None:
                if count == 1:
                    embed = discord.Embed(title="Skipped! :track_next:", color=0x00FFCC, url="https://d.chulte.de")
                    await ctx.send(embed=embed, delete_after=10)
                    self.dictionary[ctx.guild.id]["voice_client"].stop()
                    if self.dictionary[ctx.guild.id]["new_song_queue"].qsize() == 0:
                        self.dictionary[ctx.guild.id]["now_playing_song"] = None
                elif count < 1:
                    embed = discord.Embed(
                        title="Please provide a valid number.", url="https://d.chulte.de", color=0x00FFCC
                    )
                    await ctx.send(embed=embed)
                    return
                else:
                    if count > self.dictionary[ctx.guild.id]["new_song_queue"].qsize():
                        embed = discord.Embed(
                            title="Skipped "
                            + str(self.dictionary[ctx.guild.id]["new_song_queue"].qsize())
                            + " Tracks! :track_next:",
                            url="https://d.chulte.de",
                            color=0x00FFCC,
                        )
                        await ctx.send(embed=embed)
                        self.dictionary[ctx.guild.id]["voice_client"].stop()
                        self.dictionary[ctx.guild.id]["now_playing_song"] = None
                    else:
                        queue = self.dictionary[ctx.guild.id]["new_song_queue"]._queue
                        self.dictionary[ctx.guild.id]["new_song_queue"]._queue = collections.deque(
                            list(queue)[(count - 1) :]
                        )
                    self.dictionary[ctx.guild.id]["voice_client"].stop()
                    embed = discord.Embed(
                        title="Skipped " + str(count) + " Tracks! :track_next:",
                        url="https://d.chulte.de",
                        color=0x00FFCC,
                    )
                    await ctx.send(embed=embed)
            else:
                embed = discord.Embed(title="Nothing is playing right now!", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed, delete_after=10)

        else:
            embed = discord.Embed(title="Not connected!", color=0x00FFCC, url="https://d.chulte.de")
            await ctx.send(embed=embed, delete_after=10)

        await asyncio.sleep(10)
        await ctx.message.delete()

    @commands.command(aliases=["unpause"])
    async def resume(self, ctx):
        try:
            if ctx.me.voice.channel != ctx.author.voice.channel:
                embed = discord.Embed(
                    title="You need to be in the same channel as the bot.", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)
                return
        except AttributeError:
            pass
        self.dictionary = self.dictionary
        if self.dictionary[ctx.guild.id]["voice_client"] is not None:
            try:
                if "pause_time" in self.dictionary[ctx.guild.id]["now_playing_song"]:
                    self.dictionary[ctx.guild.id]["now_playing_song"]["pause_duration"] += (
                        int(time.time()) - self.dictionary[ctx.guild.id]["now_playing_song"]["pause_time"]
                    )
                    self.dictionary[ctx.guild.id]["now_playing_song"]["is_paused"] = False
                self.dictionary[ctx.guild.id]["voice_client"].resume()
                embed = discord.Embed(title="Unpaused! ⏯", color=0x00FFCC, url="https://d.chulte.de")
                await ctx.send(embed=embed)
            except Exception as e:
                embed = discord.Embed(
                    title=":thinking: Nothing is running... :thinking:", color=0x00FFCC, url="https://d.chulte.de"
                )
                await ctx.send(embed=embed)

    @commands.command()
    async def reset(self, ctx):
        if self.dictionary[ctx.guild.id]["voice_client"] is not None:
            await self.dictionary[ctx.guild.id]["voice_client"].disconnect()
        if ctx.guild.id not in self.dictionary:
            self.dictionary[ctx.guild.id] = dict()
        self.dictionary[ctx.guild.id]["new_song_queue"] = Queue()
        self.dictionary[ctx.guild.id]["voice_client"] = None
        self.dictionary[ctx.guild.id]["voice_channel"] = None
        self.dictionary[ctx.guild.id]["now_playing_song"] = None
        embed = discord.Embed(
            title="I hope this resolved your issues. :smile: Click me if you want to file a bug report.",
            color=0x00FFCC,
            url="https://github.com/tooxo/Geiler-Musik-Bot/issues/new",
        )
        await ctx.send(embed=embed)

    @commands.command()
    async def restart(self, ctx, restart_string=None):
        if restart_string is None:
            embed = discord.Embed(
                title="You need to provide a valid restart key.",
                url="https://d.chulte.de/restart_token",
                color=0x00FFCC,
            )
            await ctx.send(embed=embed)
            return
        correct_string = await self.mongo.get_restart_key()
        if restart_string == correct_string:
            embed = discord.Embed(title="Restarting!", url="https://d.chulte.de", color=0x00FFCC)
            await ctx.send(embed=embed)
            await self.bot.logout()
        else:
            embed = discord.Embed(title="Wrong token!", url="https://d.chulte.de", color=0x00FFCC)
            await ctx.send(embed=embed)

    @commands.command()
    async def test(self, ctx):
        s = aiohttp.ClientSession()
        async with s.get("socks5://proxy:1080") as r:
            print(await r.text())


def setup(bot):
    bot.add_cog(DiscordBot(bot))
