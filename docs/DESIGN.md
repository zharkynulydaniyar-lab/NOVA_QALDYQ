# Qaldyq дизайн жаңартуы

2026 жылғы 30 қазан.

v3 жаңартуы: басты беттегі екі статикалық кадрдың орнына үш қозғалатын кейіпкер енгізілді. Өлшеу мен санаудың өз бөлімдері және нақты деректен жасалатын көлемді диаграммалар бар. Қазіргі нұсқаның сипаттамасы `ANIMATIONS.md` ішінде. Төмендегі иллюстрация промпттары v2 материалдары ретінде сақталған; кампус PNG-і кіру экранында қолданылады.

## Жаңарған көрініс

Қою жасыл бүйір мәзір, лайм акценті, ашық фон, оқуға ыңғайланған қаріп өлшемдері, жұмсақ көлеңке және жаңа карточкалар қолданылды. Басты бетте кампус пен ресурс циклі көрсетілген екі 3D иллюстрация бар. 01 және 02 батырмаларымен негізгі кадр ауысады. Тінтуірге жауап беретін жеңіл перспективалық параллакс бар; touch құрылғысында және `prefers-reduced-motion` қосылғанда қозғалыс қолданылмайды. Кіру экранында да кампус көрінісі бар.

Есеп процесі, рөлдер және бастапқы деректер сақталған. v2 көріністері жобаға жергілікті PNG ретінде енгізілген. v3 анимациялары мен диаграммалары жергілікті Three.js арқылы WebGL mesh ретінде жасалады. Сыртқы шрифт, CDN немесе жұмыс кезінде интернет қажет емес.

## Файлдар

- Дизайн стильдері: `C:\Users\User\PycharmProjects\Nova\static\studio.css`.
- Кампус кадры: `C:\Users\User\PycharmProjects\Nova\static\campus-3d-v2.png`.
- Ресурс циклі: `C:\Users\User\PycharmProjects\Nova\static\cycle-3d-v2.png`.
- Кадр ауыстыру мен параллакс: `static/app.js` ішіндегі `studioHero` және `bindStudio`.

Екі кадр да built-in Imagegen құралымен жасалды. CLI/API fallback қолданылмады. Бастапқы генерациялар сақталып, таңдалған файлдар жоба папкасына көшірілді. PNG мөлдірлігі сақталды. Бұл — нақты ATU ғимаратының немесе өлшенген қайта өңдеу процесінің фотосы емес, өнімге арналған иллюстрациялар.

## Кампус кадрының соңғы промпты

Use case: stylized-concept. Asset type: premium 3D illustration for a food-waste analytics web dashboard named Qaldyq (no text in image). Create a beautifully composed isometric miniature circular university campus on a floating rounded-square pale sage island. A small modern ivory university building with tall glass windows, a tiny green rooftop garden, a tasteful outdoor dining table with two chairs, a cluster of three rounded smart food waste sorting bins (forest green, pale lime, warm cream), small leafy trees, one tasteful looping green arrow ribbon subtly connecting bins and garden, a few abstract floating lime data chips. Polished high-end Blender/Octane product render, soft sculpted matte ceramic surfaces mixed with frosted glass, restrained chrome details, precise ambient occlusion, realistic contact shadows, airy daylight and beautiful soft highlights, forest green #075c46, pale lime #d5f3a2, ivory, warm beige. Three-quarter isometric view, entire island visible and centered, no elements cut off, elegant architectural miniature, sophisticated and clean rather than childish toy. Transparent background with alpha, no backdrop, no text, letters, numbers, logos, people, watermarks or interface. Square composition.

## Ресурс циклінің соңғы промпты

Use case: stylized-concept. Asset type: premium 3D sustainability illustration for a food-waste analytics dashboard. Three beautifully sculpted thick arrows forming a circular recycling loop, made of translucent sage glass and matte forest green ceramic, floating above a small rounded ivory pedestal. Inside the loop a realistic small green sprout grows from dark compost, with one subtle orange peel curl and a single coffee bean nearby. Composition feels like a high-end editorial eco technology product render, Blender / Octane quality, accurate soft reflections, ambient occlusion and contact shadows, refined studio illumination, ivory white, pale lime #d5f3a2, forest green #075c46, warm ochre detail. Three-quarter isometric view, whole subject visible and centered, premium restrained materials. Transparent background with alpha. No text, letters, logos, numbers, people, watermark or interface. Square composition.

## Тексеру

20 API интеграциялық тесті өтті. Жаңа CSS және екі PNG серверден 200 жауабымен берілетіні осы тексеруге қосылды. JavaScript синтаксисі тексерілді. Браузерде кадр ауыстыру, кіру беті, мобильді мәзір мен есеп формасы қаралды. 320, 390, 1024 және 1440 пиксель ендері тексерілді; бүкіл беттің көлденең ығысуы жоқ. Кең есеп кестелері өз контейнерінде айналады.
