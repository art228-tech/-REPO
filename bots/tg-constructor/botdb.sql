--
-- PostgreSQL database dump
--

\restrict U1YcgUTHcNpHIyE2za9u2xJjQrTxwbTv1QAiC0JvEefReGQYTKjoIsvrEZqSHnm

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: bot_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bot_users (
    id integer NOT NULL,
    bot_id integer NOT NULL,
    user_id bigint NOT NULL,
    username character varying(200),
    full_name character varying(300),
    current_step integer NOT NULL,
    completed boolean NOT NULL,
    join_ref character varying(200),
    sent_message_ids json,
    joined_at timestamp without time zone DEFAULT now() NOT NULL,
    last_activity timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: bot_users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bot_users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bot_users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bot_users_id_seq OWNED BY public.bot_users.id;


--
-- Name: scenario_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scenario_steps (
    id integer NOT NULL,
    bot_id integer NOT NULL,
    "position" integer NOT NULL,
    step_type character varying(20) NOT NULL,
    message_data json,
    has_buttons boolean NOT NULL,
    delay_after integer NOT NULL,
    waiting_text text
);


--
-- Name: scenario_steps_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scenario_steps_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scenario_steps_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scenario_steps_id_seq OWNED BY public.scenario_steps.id;


--
-- Name: sponsors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sponsors (
    id integer NOT NULL,
    step_id integer NOT NULL,
    title character varying(200) NOT NULL,
    url character varying(500) NOT NULL,
    channel_id bigint
);


--
-- Name: sponsors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sponsors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sponsors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sponsors_id_seq OWNED BY public.sponsors.id;


--
-- Name: user_step_completions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_step_completions (
    id integer NOT NULL,
    bot_user_id integer NOT NULL,
    step_id integer NOT NULL,
    completed_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_step_completions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_step_completions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_step_completions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_step_completions_id_seq OWNED BY public.user_step_completions.id;


--
-- Name: welcome_bots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.welcome_bots (
    id integer NOT NULL,
    token character varying(200) NOT NULL,
    name character varying(200) NOT NULL,
    username character varying(200),
    channel_id bigint,
    channel_title character varying(200),
    is_active boolean NOT NULL,
    delay_seconds integer NOT NULL,
    reminder_seconds integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: welcome_bots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.welcome_bots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: welcome_bots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.welcome_bots_id_seq OWNED BY public.welcome_bots.id;


--
-- Name: bot_users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_users ALTER COLUMN id SET DEFAULT nextval('public.bot_users_id_seq'::regclass);


--
-- Name: scenario_steps id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_steps ALTER COLUMN id SET DEFAULT nextval('public.scenario_steps_id_seq'::regclass);


--
-- Name: sponsors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sponsors ALTER COLUMN id SET DEFAULT nextval('public.sponsors_id_seq'::regclass);


--
-- Name: user_step_completions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_step_completions ALTER COLUMN id SET DEFAULT nextval('public.user_step_completions_id_seq'::regclass);


--
-- Name: welcome_bots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.welcome_bots ALTER COLUMN id SET DEFAULT nextval('public.welcome_bots_id_seq'::regclass);


--
-- Data for Name: bot_users; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.bot_users (id, bot_id, user_id, username, full_name, current_step, completed, join_ref, sent_message_ids, joined_at, last_activity) FROM stdin;
9	1	8165323516	dashulxxww	дᴀɯᴋᴀ я	0	f	\N	[]	2026-06-04 20:47:52.622506	2026-06-07 00:04:55.100554
18	1	7038738818	LightYagamio	𝑳 𝒊 𝒈 𝒉 𝒕 𝒀 𝒂 𝒈 𝒂 𝒎 𝒊	0	f	\N	[]	2026-06-13 20:34:31.242807	2026-06-14 06:59:56.180547
2	1	5068661005	zxbsweel	💎	0	f	\N	[]	2026-05-11 12:36:29.205773	2026-05-11 12:41:29.413239
1	1	675390384	NikitkaAi	Nikita	0	f	\N	[]	2026-05-07 11:14:41.678167	2026-05-20 21:09:13.322201
3	1	8127975251	XYESOS228671488	ДЖЕЙСОН БРОДИ	0	f	\N	[]	2026-05-16 12:04:34.704982	2026-05-20 21:14:13.615614
17	1	5540962141	skaitax	катерина	0	f	\N	[]	2026-06-13 02:40:38.629786	2026-06-13 10:00:56.681003
4	1	8049255356	pqkehduewpwk	ᅠ ︎ ︎ ︎ ︎ ᅠ ︎ ︎ ︎ ︎ ᅠ ︎	0	f	\N	[]	2026-05-26 20:29:45.672238	2026-05-26 20:40:35.753171
6	1	7042212284	Kiber_mini_cat	𝓚𝓪𝓻𝓪𝓽𝓮𝓵𝔂𝓨	0	f	\N	[]	2026-05-30 12:11:29.365713	2026-05-30 12:16:29.521678
19	1	8147734204	youtranf	rrt	0	f	\N	[]	2026-06-15 16:04:10.287803	2026-06-16 05:34:44.691378
13	1	7221111047	Den_grig9	ⲇⲉⲏ ⲅⲣυⲙⲩⲣ	0	f	\N	[]	2026-06-07 19:57:04.209428	2026-06-07 20:02:04.36883
14	1	8503682513	Oloe_vera	lucky	0	f	\N	[]	2026-06-11 09:19:18.462155	2026-06-11 09:24:18.632746
29	1	7860225471	schemiva	мелстройность	0	f	\N	[]	2026-08-02 19:55:25.587999	2026-08-02 20:00:25.771558
20	1	8442675140	Xasbiknacondicuox	Хомяк на прайме	0	f	\N	[]	2026-06-21 06:00:05.16099	2026-06-21 06:10:05.686564
8	1	6003476374	egorka_pamidorka	Егор 🤑🔥	0	f	\N	[]	2026-06-04 15:59:11.619357	2026-06-04 16:04:11.797523
12	1	6897000463	eshkereshnaa	eshkka❄️	0	f	\N	[]	2026-06-07 12:47:33.447747	2026-06-07 13:47:36.208531
27	1	7701780086	Temazanit	✝☠Тë~мАтїК☠✝	0	f	\N	[11459]	2026-07-30 09:59:23.907565	2026-08-05 06:20:27.739951
16	1	8265143409	SONYA_SAFAROVA_ORIG	Соня Сафарова💗	0	f	\N	[]	2026-06-12 08:50:48.358238	2026-06-12 14:06:02.254905
10	1	7137408091	myeatmyblood	Acidic☢#066	0	f	\N	[]	2026-06-05 19:25:01.118206	2026-06-05 19:30:01.245138
21	1	1527352496	diankaprs	диана	0	f	\N	[]	2026-06-29 10:30:26.636581	2026-06-29 10:50:27.776301
11	1	6690083849	liiooxxxx	Лисёна🫶	0	f	\N	[]	2026-06-06 21:57:16.024449	2026-06-07 08:42:40.252563
7	1	8617802897	wer8et	капустов	0	f	\N	[]	2026-05-31 06:34:41.119052	2026-05-31 06:44:41.429797
5	1	8678917602	alexandr2435	???	0	f	\N	[]	2026-05-29 23:24:41.655843	2026-06-11 12:19:04.587836
15	1	8459347265	ak_lmw	Саша	0	f	\N	[]	2026-06-11 19:05:11.336803	2026-06-11 19:10:11.520843
22	1	7766171521	Egor4ik_VIP	PAHAN4IK	0	f	\N	[]	2026-07-01 06:37:16.567129	2026-07-01 06:42:16.831263
23	1	6411335019	\N	‌‌‌‌psyhex	0	f	\N	[]	2026-07-06 20:26:45.336179	2026-07-06 20:31:45.60145
28	1	8559850071	Verite27	Dekster	0	f	\N	[]	2026-07-30 15:23:31.053682	2026-07-30 15:28:31.187415
24	1	8229365531	BcspBs	Bcsp	0	f	\N	[]	2026-07-10 19:19:07.372445	2026-07-10 19:24:07.884492
25	1	7671377094	Killracuze	𝐫𝐚𝐤𝐮𝐳𝐚𝐧 | #𝟐𝟎𝟏𝟔	0	f	\N	[]	2026-07-15 15:05:03.160985	2026-07-15 15:10:03.420753
26	1	5279865784	Chekande_G63	𝕸[̲̅a]₮вɆй	0	f	\N	[]	2026-07-16 15:42:09.39719	2026-07-16 15:47:09.690114
\.


--
-- Data for Name: scenario_steps; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.scenario_steps (id, bot_id, "position", step_type, message_data, has_buttons, delay_after, waiting_text) FROM stdin;
4	1	0	message	{"content_type": "text", "text": ".", "buttons": [[{"text": "\\ud83c\\udfb0 \\u041a\\u0440\\u0443\\u0442\\u0438\\u0442\\u044c \\u0440\\u0443\\u043b\\u0435\\u0442\\u043a\\u0443", "web_app": "https://bitsmybots2026.chickenkiller.com/roulette.html"}]]}	t	0	\N
5	1	1	message	{"content_type": "text", "text": "."}	f	0	\N
\.


--
-- Data for Name: sponsors; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.sponsors (id, step_id, title, url, channel_id) FROM stdin;
\.


--
-- Data for Name: user_step_completions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.user_step_completions (id, bot_user_id, step_id, completed_at) FROM stdin;
\.


--
-- Data for Name: welcome_bots; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.welcome_bots (id, token, name, username, channel_id, channel_title, is_active, delay_seconds, reminder_seconds, created_at) FROM stdin;
1	8763372938:AAEDOifLs4w2sFI2hM0MUd17S9-qYoQwGc8	ХАЛЯВНЫЙ ПОДАРОК 🎁	StarsoGoldBot	\N	\N	t	0	300	2026-05-07 11:14:14.348875
\.


--
-- Name: bot_users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.bot_users_id_seq', 29, true);


--
-- Name: scenario_steps_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.scenario_steps_id_seq', 5, true);


--
-- Name: sponsors_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.sponsors_id_seq', 1, false);


--
-- Name: user_step_completions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.user_step_completions_id_seq', 1, false);


--
-- Name: welcome_bots_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.welcome_bots_id_seq', 1, true);


--
-- Name: bot_users bot_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_users
    ADD CONSTRAINT bot_users_pkey PRIMARY KEY (id);


--
-- Name: scenario_steps scenario_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_steps
    ADD CONSTRAINT scenario_steps_pkey PRIMARY KEY (id);


--
-- Name: sponsors sponsors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sponsors
    ADD CONSTRAINT sponsors_pkey PRIMARY KEY (id);


--
-- Name: user_step_completions user_step_completions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_step_completions
    ADD CONSTRAINT user_step_completions_pkey PRIMARY KEY (id);


--
-- Name: welcome_bots welcome_bots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.welcome_bots
    ADD CONSTRAINT welcome_bots_pkey PRIMARY KEY (id);


--
-- Name: welcome_bots welcome_bots_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.welcome_bots
    ADD CONSTRAINT welcome_bots_token_key UNIQUE (token);


--
-- Name: bot_users bot_users_bot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bot_users
    ADD CONSTRAINT bot_users_bot_id_fkey FOREIGN KEY (bot_id) REFERENCES public.welcome_bots(id);


--
-- Name: scenario_steps scenario_steps_bot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scenario_steps
    ADD CONSTRAINT scenario_steps_bot_id_fkey FOREIGN KEY (bot_id) REFERENCES public.welcome_bots(id);


--
-- Name: sponsors sponsors_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sponsors
    ADD CONSTRAINT sponsors_step_id_fkey FOREIGN KEY (step_id) REFERENCES public.scenario_steps(id);


--
-- Name: user_step_completions user_step_completions_bot_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_step_completions
    ADD CONSTRAINT user_step_completions_bot_user_id_fkey FOREIGN KEY (bot_user_id) REFERENCES public.bot_users(id);


--
-- Name: user_step_completions user_step_completions_step_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_step_completions
    ADD CONSTRAINT user_step_completions_step_id_fkey FOREIGN KEY (step_id) REFERENCES public.scenario_steps(id);


--
-- PostgreSQL database dump complete
--

\unrestrict U1YcgUTHcNpHIyE2za9u2xJjQrTxwbTv1QAiC0JvEefReGQYTKjoIsvrEZqSHnm

