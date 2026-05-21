export interface SolarTerm {
  nameJP: string;
  reading: string;
  description: string;
}

export interface MicroSeason {
  nameJP: string;
  reading: string;
  description: string;
}

export const solarTerms: SolarTerm[] = [
  { nameJP: "立春", reading: "りっしゅん", description: "春の気配が立ち始める時期。" },
  { nameJP: "雨水", reading: "うすい", description: "空から降る雪が雨に変わり、氷が解けて水になる時期。" },
  { nameJP: "啓蟄", reading: "けいちつ", description: "冬ごもりをしていた虫たちが土の中から出てくる時期。" },
  { nameJP: "春分", reading: "しゅんぶん", description: "昼夜の長さがほぼ等しくなる時期。" },
  { nameJP: "清明", reading: "せいめい", description: "万物が清らかで生き生きとしてくる時期。" },
  { nameJP: "穀雨", reading: "こくう", description: "田畑を潤す雨が降り、種まきの季節になる時期。" },
  { nameJP: "立夏", reading: "りっか", description: "夏の気配が立ち始める時期。" },
  { nameJP: "小満", reading: "しょうまん", description: "万物が次第に成長して満ち始める時期。" },
  { nameJP: "芒種", reading: "ぼうしゅ", description: "稲などの穂が出る植物の種をまく時期。" },
  { nameJP: "夏至", reading: "げし", description: "一年のうちで最も昼の時間が長くなる時期。" },
  { nameJP: "小暑", reading: "しょうしょ", description: "暑さが本格的になり始める時期。" },
  { nameJP: "大暑", reading: "たいしょ", description: "一年のうちで最も暑い時期。" },
  { nameJP: "立秋", reading: "りっしゅう", description: "秋の気配が立ち始める時期。" },
  { nameJP: "処暑", reading: "しょしょ", description: "暑さが峠を越え、収まる時期。" },
  { nameJP: "白露", reading: "はくろ", description: "草花に白い露が降りる時期。" },
  { nameJP: "秋分", reading: "しゅうぶん", description: "春分と同様、昼夜の長さがほぼ等しくなる時期。" },
  { nameJP: "寒露", reading: "かんろ", description: "露が冷たく感じられ、草木が色づき始める時期。" },
  { nameJP: "霜降", reading: "そうこう", description: "霜が降り始める時期。" },
  { nameJP: "立冬", reading: "りっとう", description: "冬の気配が立ち始める時期。" },
  { nameJP: "小雪", reading: "しょうせつ", description: "わずかな雪が降り始める時期。" },
  { nameJP: "大雪", reading: "たいせつ", description: "本格的に雪が降り積もる時期。" },
  { nameJP: "冬至", reading: "とうじ", description: "一年のうちで最も昼の時間が短くなる時期。" },
  { nameJP: "小寒", reading: "しょうかん", description: "「寒の入り」とも呼ばれ、寒さが厳しくなり始める時期。" },
  { nameJP: "大寒", reading: "だいかん", description: "一年のうちで最も寒さが厳しくなる時期。" }
];

export const microSeasons: MicroSeason[] = [
  { nameJP: "東風解凍", reading: "はるかぜこおりをとく", description: "東風が氷を解かし始める。" },
  { nameJP: "黄鶯睍睆", reading: "うぐいすなく", description: "山里で鶯が鳴き始める。" },
  { nameJP: "魚上氷", reading: "うおこおりをいずる", description: "割れた氷の間から魚が飛び跳ねる。" },
  { nameJP: "土脉潤起", reading: "つちのしょううるおいおこる", description: "冷たい雨が降って、土が湿り気を含む。" },
  { nameJP: "霞始靆", reading: "かすみはじめてたなびく", description: "霞がたなびき始める。" },
  { nameJP: "草木萌動", reading: "そうもくめばえいずる", description: "草木が芽吹き始める。" },
  { nameJP: "蟄虫啓戸", reading: "すごもりのむしとをひらく", description: "冬ごもりの虫が地上に這い出る。" },
  { nameJP: "桃始笑", reading: "ももはじめてわらう", description: "桃の花が咲き始める。" },
  { nameJP: "菜虫化蝶", reading: "なむしちょうとなる", description: "菜虫が羽化して紋白蝶になる。" },
  { nameJP: "雀始巣", reading: "すずめはじめてすくう", description: "雀が巣を作り始める。" },
  { nameJP: "桜始開", reading: "さくらはじめてさく", description: "桜の花が咲き始める。" },
  { nameJP: "雷乃発声", reading: "かみなりすなわちこえをはっす", description: "遠くで雷の音がし始める。" },
  { nameJP: "玄鳥至", reading: "つばめきたる", description: "南から燕がやって来る。" },
  { nameJP: "鴻雁北", reading: "こうがんかえる", description: "雁が北へ帰っていく。" },
  { nameJP: "虹始見", reading: "にじはじめてあらわる", description: "雨上がりに虹が見え始める。" },
  { nameJP: "葭始生", reading: "あしはじめてしょうず", description: "葭が芽吹き始める。" },
  { nameJP: "霜止出苗", reading: "しもやみてなえいずる", description: "霜が降りなくなり、稲の苗が育つ。" },
  { nameJP: "牡丹華", reading: "ぼたんはなさく", description: "牡丹の花が咲く。" },
  { nameJP: "蛙始鳴", reading: "かわずはじめてなく", description: "蛙が鳴き始める。" },
  { nameJP: "蚯蚓出", reading: "みみずいずる", description: "蚯蚓が地上に這い出る。" },
  { nameJP: "竹笋生", reading: "たけのこしょうず", description: "竹の子がひょっこり顔を出す。" },
  { nameJP: "蚕起食桑", reading: "かいこおきてくわをはむ", description: "蚕が桑の葉を盛んに食べ始める。" },
  { nameJP: "紅花栄", reading: "べにばなさかえ", description: "紅花が辺り一面に咲き誇る。" },
  { nameJP: "麦秋至", reading: "むぎのときいたる", description: "麦が実り、収穫の時期を迎える。" },
  { nameJP: "蟷螂生", reading: "かまきりしょうず", description: "蟷螂が孵化して姿を現す。" },
  { nameJP: "腐草為螢", reading: "くされたるくさほたるとなる", description: "枯れた草が蒸れて蛍になる。" },
  { nameJP: "梅子黄", reading: "うめのみきばむ", description: "梅の実が黄色く色づく。" },
  { nameJP: "乃東枯", reading: "なつかれくさかる", description: "夏枯草が枯れる。" },
  { nameJP: "菖蒲華", reading: "あやめはなさく", description: "あやめの花が咲き始める。" },
  { nameJP: "半夏生", reading: "はんげしょうず", description: "半夏が生え始める。" },
  { nameJP: "温風至", reading: "あつかぜいたる", description: "温かい風が吹き始める。" },
  { nameJP: "蓮始開", reading: "はすはじめてさく", description: "蓮の花が咲き始める。" },
  { nameJP: "鷹乃学習", reading: "たかすなわちわざをならう", description: "鷹の幼鳥が飛ぶ術を学ぶ。" },
  { nameJP: "桐始結花", reading: "きりはじめてはなをむすぶ", description: "桐の実がなり始める。" },
  { nameJP: "土潤溽暑", reading: "つちうるおうてむしあつし", description: "土が湿って蒸し暑くなる。" },
  { nameJP: "大雨時行", reading: "たいうときどきふる", description: "時折、激しい雨が降る。" },
  { nameJP: "涼風至", reading: "すずかぜいたる", description: "涼しい風が吹き始める。" },
  { nameJP: "寒蝉鳴", reading: "ひぐらしなく", description: "ひぐらしが鳴き始める。" },
  { nameJP: "蒙霧升降", reading: "ふかききりまとう", description: "深い霧が立ち込める。" },
  { nameJP: "綿柎開", reading: "わたのはなひらく", description: "綿を包むガクが開き始める。" },
  { nameJP: "天地始粛", reading: "てんちはじめてさむし", description: "ようやく夏の暑さが静まる。" },
  { nameJP: "禾乃登", reading: "こくものすなわちみのる", description: "稲が実り、穂を垂らす。" },
  { nameJP: "草露白", reading: "くさのつゆしろし", description: "草に降りた露が白く光る。" },
  { nameJP: "鶺鴒鳴", reading: "せきれいなく", description: "鶺鴒が鳴き始める。" },
  { nameJP: "玄鳥去", reading: "つばめさる", description: "燕が南へ帰っていく。" },
  { nameJP: "雷乃収声", reading: "かみなりすなわちこえをおさむ", description: "雷が鳴らなくなる。" },
  { nameJP: "蟄虫坏戸", reading: "むしかくれてとをふさぐ", description: "虫が土の中で冬ごもりの支度をする。" },
  { nameJP: "水始涸", reading: "みずはじめてかる", description: "田んぼの水を抜き、収穫の準備をする。" },
  { nameJP: "鴻雁来", reading: "こうがんきたる", description: "雁が北から渡ってくる。" },
  { nameJP: "菊花開", reading: "きくのはなひらく", description: "菊の花が咲き始める。" },
  { nameJP: "蟋蟀在戸", reading: "きりぎりすとにあり", description: "秋の虫が戸口で鳴き始める。" },
  { nameJP: "霜始降", reading: "しもはじめてふる", description: "霜が初めて降りる。" },
  { nameJP: "霎時施", reading: "こさめときどきふる", description: "小雨がパラパラと降る。" },
  { nameJP: "楓蔦黄", reading: "もみじつたきばむ", description: "楓や蔦が色づく。" },
  { nameJP: "山茶始開", reading: "つばきはじめてさく", description: "山茶花の花が咲き始める。" },
  { nameJP: "地始凍", reading: "ちはじめてこおる", description: "大地が凍り始める。" },
  { nameJP: "金盞香", reading: "きんせんかさく", description: "水仙の花が咲き始める。" },
  { nameJP: "虹蔵不見", reading: "にじかくれてみえず", description: "雪が降り始め、虹が見えなくなる。" },
  { nameJP: "朔風払葉", reading: "きたかぜこのはをはらう", description: "北風が木の葉を払い落とす。" },
  { nameJP: "橘始黄", reading: "たちばなはじめてきばむ", description: "橘の実が黄色くなり始める。" },
  { nameJP: "閉塞成冬", reading: "そらさむくふゆとなる", description: "天地の気が塞がり、真冬となる。" },
  { nameJP: "熊蟄穴", reading: "くまあなにこもる", description: "熊が冬ごもりのために穴に入る。" },
  { nameJP: "鱖魚群", reading: "さけのうおむらがる", description: "鮭が産卵のために川を遡上する。" },
  { nameJP: "乃東生", reading: "なつかれくさしょうず", description: "夏枯草が芽を出す。" },
  { nameJP: "麋角解", reading: "さわしかのつのおつ", description: "大鹿の角が落ち、生え変わる。" },
  { nameJP: "雪下出麦", reading: "ゆきわたりてむぎいずる", description: "雪の下で麦が芽を出す。" },
  { nameJP: "芹乃栄", reading: "せりすなわちさかえ", description: "芹が盛んに茂り始める。" },
  { nameJP: "水泉動", reading: "しみずあたたかをふくむ", description: "凍った泉が溶け、動き始める。" },
  { nameJP: "雉始雊", reading: "きじはじめてなく", description: "雄の雉が鳴き始める。" },
  { nameJP: "款冬華", reading: "ふきのはなはなさく", description: "蕗のとうが顔を出す。" },
  { nameJP: "水沢腹堅", reading: "さわみずこおりつめる", description: "沢の氷が厚く張り詰める。" },
  { nameJP: "鶏始乳", reading: "にわとりはじめてとやにつく", description: "鶏が卵を産み始める。" }
];

export const getSolarTerm = (date: Date): SolarTerm => {
  const dayOfYear = Math.floor((date.getTime() - new Date(date.getFullYear(), 0, 0).getTime()) / 86400000);
  const termIndex = Math.floor(dayOfYear / (365 / 24)) % 24;
  return solarTerms[termIndex];
};

export const getMicroSeason = (date: Date): MicroSeason => {
  const dayOfYear = Math.floor((date.getTime() - new Date(date.getFullYear(), 0, 0).getTime()) / 86400000);
  const seasonIndex = Math.floor(dayOfYear / (365 / 72)) % 72;
  return microSeasons[seasonIndex];
};
