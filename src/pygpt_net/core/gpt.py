#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ================================================== #
# This file is a part of PYGPT package               #
# Website: https://pygpt.net                         #
# GitHub:  https://github.com/szczyglis-dev/py-gpt   #
# MIT License                                        #
# Created By  : Marcin Szczygliński                  #
# Updated Date: 2023.12.02 21:00:00                  #
# ================================================== #
import base64
import os
import re

from openai import OpenAI
from .tokens import num_tokens_prompt, num_tokens_extra, num_tokens_from_messages, num_tokens_completion, \
    num_tokens_only
from .context import Context, ContextItem


class Gpt:
    def __init__(self, config, context):
        """
        GPT Wrapper

        :param config: Config object
        """
        self.config = config
        self.context = context

        self.ai_name = None
        self.user_name = None
        self.system_prompt = None
        self.input_tokens = 0
        self.attachments = {}

        if not self.config.initialized:
            self.config.init()

    def init(self):
        """Initializes OpenAI API key"""
        pass
        #openai.api_key = self.config.data["api_key"]
        #openai.organization = self.config.data["organization_key"]

    def completion(self, prompt, max_tokens, stream_mode=False):
        """
        Calls OpenAI API for completion

        :param prompt: Prompt (user message)
        :param max_tokens: Max output tokens
        :param stream_mode: Stream mode
        :return: Response dict or stream chunks
        """
        # build prompt message
        message = self.build_completion(prompt)

        # prepare stop word if user_name is set
        stop = None
        if self.user_name is not None and self.user_name != '':
            stop = [self.user_name + ':']

        client = OpenAI(
            # This is the default and can be omitted
            api_key=self.config.data["api_key"],
            organization=self.config.data["organization_key"],
        )
        response = client.completions.create(
            prompt=message,
            model=self.config.data['model'],
            max_tokens=int(max_tokens),
            temperature=self.config.data['temperature'],
            top_p=self.config.data['top_p'],
            frequency_penalty=self.config.data['frequency_penalty'],
            presence_penalty=self.config.data['presence_penalty'],
            stop=stop,
            stream=stream_mode,
        )
        return response

    def chat(self, prompt, max_tokens, stream_mode=False):
        """
        Call OpenAI API for chat

        :param prompt: Prompt (user message)
        :param max_tokens: Max output tokens
        :param stream_mode: Stream mode
        :return: Response dict or stream chunks
        """
        client = OpenAI(
            # This is the default and can be omitted
            api_key=self.config.data["api_key"],
            organization=self.config.data["organization_key"],
        )

        # build chat messages
        messages = self.build_chat_messages(prompt)
        response = client.chat.completions.create(
            messages=messages,
            model=self.config.data['model'],
            max_tokens=int(max_tokens),
            temperature=self.config.data['temperature'],
            top_p=self.config.data['top_p'],
            frequency_penalty=self.config.data['frequency_penalty'],
            presence_penalty=self.config.data['presence_penalty'],
            stop=None,
            stream=stream_mode,
        )
        return response

    def vision(self, prompt, max_tokens, stream_mode=False):
        """
        Call OpenAI API for chat with vision

        :param prompt: Prompt (user message)
        :param max_tokens: Max output tokens
        :param stream_mode: Stream mode
        :return: Response dict or stream chunks
        """
        client = OpenAI(
            # This is the default and can be omitted
            api_key=self.config.data["api_key"],
            organization=self.config.data["organization_key"],
        )

        # build chat messages
        messages = self.build_chat_messages(prompt)
        response = client.chat.completions.create(
            messages=messages,
            model=self.config.data['model'],
            max_tokens=int(max_tokens),
            stream=stream_mode,
        )
        return response

    def reset_tokens(self):
        """Resets input tokens counter"""
        self.input_tokens = 0

    def build_chat_messages(self, prompt, system_prompt=None):
        """
        Builds chat messages dict

        :param prompt: Prompt
        :param system_prompt: System prompt (optional)
        :return: Messages dict
        """
        messages = []

        # tokens config
        model = self.config.data['model']
        mode = self.config.data['mode']
        used_tokens = self.count_used_tokens(prompt)
        max_tokens = self.config.data['max_total_tokens']
        model_ctx = self.config.get_model_ctx(model)
        if max_tokens > model_ctx:
            max_tokens = model_ctx

        # names
        ai_name = "assistant"  # default
        user_name = "user"  # default
        if self.user_name is not None and self.user_name != "":
            user_name = self.user_name
        if self.ai_name is not None and self.ai_name != "":
            ai_name = self.ai_name

        # input tokens: reset
        self.reset_tokens()

        # append initial (system) message
        if system_prompt is not None and system_prompt != "":
            messages.append({"role": "system", "content": system_prompt})
        else:
            if self.system_prompt is not None and self.system_prompt != "":
                messages.append({"role": "system", "content": self.system_prompt})

        # append messages from context (memory)
        if self.config.data['use_context']:
            items = self.context.get_prompt_items(model, used_tokens, max_tokens)
            for item in items:
                # input
                if item.input is not None and item.input != "":
                    if mode == "chat":
                        messages.append({"role": "system", "name": user_name, "content": item.input})
                    elif mode == "vision":
                        content = self.build_vision_content(item.input)
                        messages.append({"role": "user", "content": content})

                # output
                if item.output is not None and item.output != "":
                    if mode == "chat":
                        messages.append({"role": "system", "name": ai_name, "content": item.output})
                    elif mode == "vision":
                        content = self.build_vision_content(item.output)
                        messages.append({"role": "assistant", "content": content})

        # append current prompt
        if mode == "chat":
            messages.append({"role": "user", "content": str(prompt)})
        elif mode == "vision":
            content = self.build_vision_content(prompt, append_attachments=True)
            messages.append({"role": "user", "content": content})

        # input tokens: update
        self.input_tokens += num_tokens_from_messages(messages, model)

        return messages

    def build_vision_content(self, text, append_attachments=False):
        """
        Builds vision content

        :param text: Text
        :param append_attachments: Append attachments
        :return: Content dict
        """
        content = [{"type": "text", "text": str(text)}]

        # extract URLs from prompt
        urls = self.extract_urls(text)
        if len(urls) > 0:
            for url in urls:
                content.append({"type": "image_url", "image_url": {"url": url}})

        # local images
        if append_attachments:
            for uuid in self.attachments:
                attachment = self.attachments[uuid]
                if os.path.exists(attachment.path):
                    # check if it's an image
                    if self.is_image(attachment.path):
                        base64_image = self.encode_image(attachment.path)
                        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})

        return content

    def build_completion(self, prompt):
        """
        Builds completion string

        :param prompt: Prompt (current)
        :return: Message string (parsed with context)
        """
        message = ""

        # tokens config
        model = self.config.data['model']
        used_tokens = self.count_used_tokens(prompt)
        max_tokens = self.config.data['max_total_tokens']
        model_ctx = self.config.get_model_ctx(model)
        if max_tokens > model_ctx:
            max_tokens = model_ctx

        # input tokens: reset
        self.reset_tokens()

        if self.system_prompt is not None and self.system_prompt != "":
            message += self.system_prompt

        if self.config.data['use_context']:
            items = self.context.get_prompt_items(model, used_tokens, max_tokens)
            for item in items:
                if item.input_name is not None \
                        and item.output_name is not None \
                        and item.input_name != "" \
                        and item.output_name != "":
                    if item.input is not None and item.input != "":
                        message += "\n" + item.input_name + ": " + item.input
                    if item.output is not None and item.output != "":
                        message += "\n" + item.output_name + ": " + item.output
                else:
                    if item.input is not None and item.input != "":
                        message += "\n" + item.input
                    if item.output is not None and item.output != "":
                        message += "\n" + item.output

        # append names
        if self.user_name is not None \
                and self.ai_name is not None \
                and self.user_name != "" \
                and self.ai_name != "":
            message += "\n" + self.user_name + ": " + str(prompt)
            message += "\n" + self.ai_name + ":"
        else:
            message += "\n" + str(prompt)

        # input tokens: update
        self.input_tokens += num_tokens_completion(message, model)

        return message

    def count_used_tokens(self, input_text):
        """
        Counts used tokens

        :param input_text: Input text
        :return: Used tokens
        """
        model = self.config.data['model']
        mode = self.config.data['mode']
        tokens = 0
        if mode == "chat" or mode == "vision":
            tokens += num_tokens_prompt(self.system_prompt, "", model)  # init (system) prompt
            tokens += num_tokens_only("system", model)
            tokens += num_tokens_prompt(input_text, "", model)  # current input
            tokens += num_tokens_only("user", model)
        elif mode == "completion":
            tokens += num_tokens_only(self.system_prompt, model)  # init (system) prompt
            tokens += num_tokens_only(input_text, model)  # current input
        tokens += self.config.data['context_threshold']  # context threshold (reserved for next output)
        tokens += num_tokens_extra(model)  # extra tokens (required for output)
        return tokens

    def quick_call(self, prompt, sys_prompt, append_context=False, max_tokens=500):
        """
        Calls OpenAI API with custom prompt

        :param prompt: User input (prompt)
        :param sys_prompt: System input (prompt)
        :param append_context: Append context (memory)
        :param max_tokens: Max output tokens
        :return: Response text
        """
        client = OpenAI(
            # This is the default and can be omitted
            api_key=self.config.data["api_key"],
            organization=self.config.data["organization_key"],
        )

        if append_context:
            messages = self.build_chat_messages(prompt, sys_prompt)
        else:
            messages = []
            messages.append({"role": "system", "content": sys_prompt})
            messages.append({"role": "user", "content": prompt})
        try:
            response = client.chat.completions.create(
                messages=messages,
                model="gpt-3.5-turbo",
                max_tokens=max_tokens,
                temperature=1.0,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                stop=None,
            )
            print(response)
            return response.choices[0].message.content
        except Exception as e:
            print("Error in custom call: " + str(e))

    def call(self, prompt, ctx=None, stream_mode=False):
        """
        Calls OpenAI API

        :param prompt: User input (prompt)
        :param ctx: Context item (memory)
        :param stream_mode: Stream mode (default: False)
        :return: Context item (memory)
        """
        # prepare max tokens
        mode = self.config.data['mode']
        model_tokens = self.config.get_model_tokens(self.config.data['model'])
        max_tokens = self.config.data['max_output_tokens']
        if max_tokens > model_tokens:
            max_tokens = model_tokens

        # minimum 1 token is required
        if max_tokens < 1:
            max_tokens = 1

        # get response
        response = None
        if mode == "completion":
            response = self.completion(prompt, max_tokens, stream_mode)
        elif mode == "chat":
            response = self.chat(prompt, max_tokens, stream_mode)
        elif mode == "vision":
            response = self.vision(prompt, max_tokens, stream_mode)

        # async mode (stream)
        if stream_mode:
            # store context (memory)
            if ctx is None:
                ctx = ContextItem(self.config.data['mode'])
                ctx.set_input(prompt, self.user_name)

            ctx.stream = response
            ctx.set_output("", self.ai_name)
            ctx.input_tokens = self.input_tokens  # from global tokens calculation
            self.context.add(ctx)
            return ctx

        if response is None:
            return None

        # check for errors
        if "error" in response:
            print("Error: " + str(response["error"]))
            return None

        # get output
        output = ""
        if mode == "completion":
            output = response.choices[0].text.strip()
        elif mode == "chat" or mode == "vision":
            output = response.choices[0].message.content.strip()

        # store context (memory)
        if ctx is None:
            ctx = ContextItem(self.config.data['mode'])
            ctx.set_input(prompt, self.user_name)

        ctx.set_output(output, self.ai_name)
        ctx.set_tokens(response.usage.prompt_tokens, response.usage.completion_tokens)
        self.context.add(ctx)

        return ctx

    def clear(self):
        """Clears context (memory)"""
        self.context.clear()

    def extract_urls(self, text):
        """Extracts urls from text"""
        return re.findall(r'(https?://\S+)', text)

    def is_image(self, path):
        """Checks if url is image"""
        return path.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif', '.webp'))

    def encode_image(self, image_path):
        """
        Encodes image to base64
        :param image_path:
        :return: base64 encoded image
        """
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
