import { useState, useEffect } from "react";
import { Sparkles, Loader2 } from "lucide-react";

interface AIShootingHintProps {
  currentMonth: number;
  currentPrefecture: string;
}

export default function AIShootingHint({ currentMonth, currentPrefecture }: AIShootingHintProps) {
  const [hint, setHint] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);

    const generateHint = async () => {
      // Simulate network wait
      await new Promise(r => setTimeout(r, 600));
      
      const regionHints: Record<string, string> = {
        "北海道": "過去に「雪景色」や「流氷」、「桜」の作品が多く入賞しています。明日はこれらの被写体を低い位置から狙うと幻想的な仕上がりになるかもしれません。",
        "青森": "過去に「奥入瀬渓流」や「桜」、「雪山」の作品が多く入賞しています。明日はこれらの被写体を低い位置から狙うと幻想的な仕上がりになるかもしれません。",
        "群馬": "過去に「志賀草津高原」や「高層湿原」、「紅葉」の作品が多く入賞しています。明日はこれらの被写体を低い位置から狙うと幻想的な仕上がりになるかもしれません。",
        "長野": "過去に「志賀草津」や「アルプス」、「雪解け」の作品が多く入賞しています。明日はこれらの被写体を低い位置から狙うと幻想的な仕上がりになるかもしれません。",
        "富山": "過去に「雪の大谷」や「立山」、「ホタルイカ」の作品が多く入賞しています。明日はこれらの被写体を低い位置から狙うと幻想的な仕上がりになるかもしれません。",
        "静岡": "過去に「富士山」や「茶畑」、「海霧」の作品が多く入賞しています。明日はこれらの被写体を低い位置から狙うと幻想的な仕上がりになるかもしれません。",
        "山梨": "過去に「富士山」や「湖の逆さ富士」、「桃の花」の作品が多く入賞しています。明日はこれらの被写体を低い位置から狙うと幻想的な仕上がりになるかもしれません。"
      };

      if (active) {
        const rootArea = currentPrefecture.replace(/[都道府県]/g, '');
        const specificHint = regionHints[rootArea];
        
        if (specificHint) {
          setHint(`この時期の${currentPrefecture}では、${specificHint}`);
        } else {
          setHint(`この時期の${currentPrefecture || 'この地域'}ではまだ登録データが少ないですが、新しい視点であなただけの風景を探してみてください。`);
        }
        setLoading(false);
      }
    };
    
    generateHint();
    
    return () => { active = false; };
  }, [currentMonth, currentPrefecture]);

  return (
    <div className="w-full mt-8 mb-12 bg-emerald-950 border border-emerald-500/30 rounded-xl p-6 md:p-8 relative overflow-hidden shadow-2xl">
      <div className="absolute top-0 right-0 p-8 opacity-5">
        <Sparkles className="w-32 h-32 text-emerald-200" />
      </div>
      <h3 className="text-lg md:text-xl font-serif text-emerald-300 font-bold mb-4 flex items-center gap-2">
        <Sparkles className="w-6 h-6" /> AI 撮影のヒント
      </h3>
      {loading ? (
        <div className="flex items-center gap-3 text-emerald-500 font-serif">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>最新の過去データからパーソナライズされたアドバイスを展開中...</span>
        </div>
      ) : (
        <p className="text-white text-base leading-relaxed relative z-10 font-serif">
          {hint}
        </p>
      )}
    </div>
  );
}
