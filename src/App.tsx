// Firebase Mocks
const db: any = {};
enum OperationType {
  CREATE = 'create',
  UPDATE = 'update',
  DELETE = 'delete',
  LIST = 'list',
  GET = 'get',
  WRITE = 'write',
}

interface FirestoreErrorInfo {
  error: string;
  operationType: string;
  path: string | null;
  authInfo: {
    userId?: string | null;
    email?: string | null;
    emailVerified?: boolean | null;
    isAnonymous?: boolean | null;
    tenantId?: string | null;
    providerInfo?: {
      providerId?: string | null;
      email?: string | null;
    }[];
  }
}

const handleFirestoreError = (error: unknown, operationType: string, path: string | null) => {
  const errInfo: FirestoreErrorInfo = {
    error: error instanceof Error ? error.message : String(error),
    authInfo: {
      userId: 'admin', // In this demo/simulation we assume admin
      email: 'admin@example.com',
      emailVerified: true,
      isAnonymous: false,
      tenantId: null,
      providerInfo: []
    },
    operationType,
    path
  }
  console.error('Firestore Error: ', JSON.stringify(errInfo));
  throw new Error(JSON.stringify(errInfo));
};
const collection = (...args: any[]): any => {};
const query = (...args: any[]): any => {};
const orderBy = (...args: any[]) => {};
const doc = (...args: any[]): any => {};
const onSnapshot = (...args: any[]) => () => {};
const serverTimestamp = () => new Date().toISOString();
/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { motion, useScroll, useTransform, AnimatePresence } from "motion/react";
import SunCalc from "suncalc";
import { 
  Camera, 
  BookOpen, 
  Calendar, 
  Mountain, 
  Mail, 
  Instagram, 
  Facebook, 
  Twitter, 
  Trophy,
  Users,
  ChevronRight, 
  Menu, 
  X,
  Search,
  ShoppingBag,
  ArrowLeft,
  Clock,
  Tag,
  LayoutDashboard,
  Plus,
  Edit,
  Trash2,
  Eye,
  LogOut,
  LogIn,
  Save,
  FileText,
  BarChart3,
  Sunrise,
  Sunset,
  Moon,
  ArrowUp,
  ArrowDown
} from "lucide-react";
import React, { useState, useEffect, ReactNode, useMemo } from "react";
import { Routes, Route, Link, useParams, useLocation, useNavigate, Navigate } from "react-router-dom";
import Markdown from "react-markdown";

import { LogoLandscape, LogoIcon } from "./components/BrandLogo";

// Fallback blog data for initial setup
import { blogPosts, BlogPost } from "./blogData";
import ReferencePage from "./components/ReferencePage";
import ArchivePage from "./components/ArchivePage";
import AISummaryPage from "./components/AISummaryPage";
import ContestDatabasePage from "./ContestDatabasePage";

import AdminSeasonalNews from './components/AdminSeasonalNews';
import ImportFirebasePage from "./components/ImportFirebasePage";
import { db as realDb } from "./firebase";
import { 
  collection as realCollection, 
  getDocsFromServer as realGetDocsFromServer,
  getDoc as realGetDoc,
  doc as realDoc,
  setDoc as realSetDoc,
  serverTimestamp as realServerTimestamp,
  onSnapshot as realOnSnapshot,
  query as realQuery,
  orderBy as realOrderBy,
  limit as realLimit,
  deleteDoc as realDeleteDoc
} from "firebase/firestore";


/**
 * Types for the application
 */
interface DBPost extends Omit<BlogPost, 'id'> {
  id?: string;
  views: number;
  authorId: string;
  createdAt: any;
  updatedAt: any;
}

interface SlideshowImage {
  url: string;
  caption?: string;
}

interface SlideshowConfig {
  images: SlideshowImage[] | string[];
  updatedAt: any;
}

interface GalleryItem {
  src: string;
  labelJP: string;
  labelEN: string;
}

interface GalleryConfig {
  items: GalleryItem[];
  updatedAt: any;
}

interface LatestIssueConfig {
  coverImage: string;
  title: string;
  description: string;
  purchaseUrl: string;
  price: string;
  releaseDate: string;
  features: string[];
  updatedAt: any;
}

// Helper to convert Google Drive links to direct image links
const getDirectImageUrl = (url: string) => {
  if (!url) return "";
  // Handle Google Drive links
  if (url.includes("drive.google.com")) {
    const match = url.match(/\/file\/d\/([^/]+)/) || url.match(/id=([^&]+)/) || url.match(/\/d\/([^/]+)/);
    if (match && match[1]) {
      return `https://lh3.googleusercontent.com/d/${match[1]}=w1000`; // Use lh3 which allows hotlinking
    }
  }
  return url;
};

import { auth, googleProvider } from "./firebase";
import { signInWithPopup, signOut, onAuthStateChanged, User } from "firebase/auth";

export const signInWithGoogle = async () => {
  try {
    await signInWithPopup(auth, googleProvider);
  } catch (error: any) {
    console.error("Error signing in with Google", error);
    alert(`ログインエラー: ${error.message || "ポップアップがブロックされたか、設定が不足しています"}`);
  }
};

export const logout = async () => {
  try {
    await signOut(auth);
  } catch (error) {
    console.error("Error signing out", error);
  }
};

const useAuth = () => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      setUser(user);
      // In a real app, you would check a Firestore `roles` collection or custom claims.
      // Here, we'll allow specific emails or any authenticated user for demo purposes, 
      // but let's check exact email as an example of admin auth.
      if (user && user.email === "kaoru@fukei-shashin.co.jp") {
        setIsAdmin(true);
      } else {
        // Alternatively, if you want to allow any logged-in Google account for now during development:
        // setIsAdmin(!!user); 
        // For strict security, only true for kaoru@fukei-shashin.co.jp
        setIsAdmin(user?.email === "kaoru@fukei-shashin.co.jp");
      }
      setLoading(false);
    });
    return () => unsubscribe();
  }, []);

  return { user, loading, isAdmin };
};

  const Logo = ({ isScrolled, isHomePage }: { isScrolled: boolean; isHomePage: boolean }) => {
    const variant = isScrolled || !isHomePage ? "dark" : "bright";
  
    return (
      <Link to="/" className="flex items-center" aria-label="トップページに戻る">
        {/* desktop & mobile: Landscape logo for full brand visibility */}
        <LogoLandscape variant={variant} className="h-7 md:h-9 w-auto" />
      </Link>
    );
  };
  
  const Navbar = () => {
    const [isScrolled, setIsScrolled] = useState(false);
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
    const location = useLocation();
    const isHomePage = location.pathname === "/";
    const isAdminPage = location.pathname.startsWith('/admin') || location.pathname === '/login';
  
    useEffect(() => {
      setIsMobileMenuOpen(false);
    }, [location.pathname]);
  
    useEffect(() => {
      const handleScroll = () => {
        setIsScrolled(window.scrollY > 50);
      };
      window.addEventListener("scroll", handleScroll);
      return () => window.removeEventListener("scroll", handleScroll);
    }, []);
  
    if (isAdminPage) return null;
  
    const navLinks = [
      { name: "撮影リファレンス［LINE］", href: "/reference" },
      { name: "『風景写真』最新号", href: isHomePage ? "#magazine" : "/#magazine" },
      { name: "お知らせ", href: "/blog" },
      // { name: "ギャラリー", href: isHomePage ? "#gallery" : "/#gallery" },
      // { name: "ライブラリ", href: isHomePage ? "#library" : "/#library" },
      // { name: "公式ショップ", href: isHomePage ? "#shop" : "/#shop" },
      { name: "作品募集中", href: isHomePage ? "#contest" : "/#contest" },
      { name: "お問い合わせ", href: isHomePage ? "#contact" : "/#contact" },
    ];
  
    return (
      <nav className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${isScrolled || !isHomePage ? "bg-white/90 backdrop-blur-md shadow-sm py-3" : "bg-transparent py-4 md:py-5"}`}>
        <div className="max-w-7xl mx-auto px-4 md:px-6 flex justify-between items-center">
          <div className="flex items-center gap-2 flex-shrink-0 mr-4">
            <Logo isScrolled={isScrolled} isHomePage={isHomePage} />
          </div>
  
          {/* Desktop Nav */}
          <div className="hidden md:flex items-center gap-3 lg:gap-5 flex-wrap justify-end">
            {navLinks.map((link) => (
              link.href.startsWith("/") && !link.href.includes("#") ? (
                <Link
                  key={link.name}
                  to={link.href}
                  className={`text-[11px] lg:text-xs font-bold hover:opacity-70 transition-opacity whitespace-nowrap flex items-center gap-1 ${isScrolled || !isHomePage ? "text-gray-800" : "text-white"}`}
                >
                  {link.name}
                </Link>
              ) : (
                <a 
                  key={link.name} 
                  href={link.href} 
                  className={`text-[11px] lg:text-xs font-bold hover:opacity-70 transition-opacity whitespace-nowrap ${isScrolled || !isHomePage ? "text-gray-800" : "text-white"}`}
                >
                  {link.name}
                </a>
              )
            ))}
            <div className="flex items-center gap-3 ml-2">
              <Search className={`w-4 h-4 cursor-pointer ${isScrolled || !isHomePage ? "text-gray-800" : "text-white"}`} />
              <ShoppingBag className={`w-4 h-4 cursor-pointer ${isScrolled || !isHomePage ? "text-gray-800" : "text-white"}`} />
            </div>
          </div>
  
          {/* Mobile Menu Toggle */}
          <button 
            className="md:hidden"
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          >
            {isMobileMenuOpen ? (
              <X className={isScrolled ? "text-gray-800" : "text-white"} />
            ) : (
              <Menu className={isScrolled ? "text-gray-800" : "text-white"} />
            )}
          </button>
        </div>

      {/* Mobile Nav */}
      {isMobileMenuOpen && (
        <motion.div 
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="absolute top-full left-0 right-0 bg-white shadow-xl p-6 md:hidden"
        >
          <div className="flex flex-col gap-4">
            {navLinks.map((link) => (
              link.href.startsWith("/") && !link.href.includes("#") ? (
                <Link
                  key={link.name}
                  to={link.href}
                  className="text-gray-800 text-lg font-medium border-b border-gray-100 pb-2 flex items-center gap-2"
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  {link.name}
                </Link>
              ) : (
                <a 
                  key={link.name} 
                  href={link.href} 
                  className="text-gray-800 text-lg font-medium border-b border-gray-100 pb-2"
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  {link.name}
                </a>
              )
            ))}
          </div>
        </motion.div>
      )}
    </nav>
  );
};

const Hero = ({ onIssueClick, onSubClick }: { onIssueClick: () => void; onSubClick: () => void }) => {
  const { scrollY } = useScroll();
  const y = useTransform(scrollY, [0, 500], [0, 200]);
  const [currentImageIndex, setCurrentImageIndex] = useState(0);
  const [remoteImages, setRemoteImages] = useState<{url: string, caption?: string}[] | null>(null);
  const [location, setLocation] = useState<{ lat: number; lng: number } | null>(null);

  const [issueTitle, setIssueTitle] = useState("隔月刊『風景写真』 2026年 5-6月号");

  useEffect(() => {
    const unsub = realOnSnapshot(realDoc(realDb, "settings", "latest_issue"), (snapshot) => {
      if (snapshot.exists()) {
        const data = snapshot.data() as LatestIssueConfig;
        if (data.title) {
          setIssueTitle(data.title.replace(/\n/g, " "));
        }
      }
    }, (error) => console.error("Latest Issue onSnapshot error:", error));
    return () => unsub();
  }, []);

  useEffect(() => {
    const defaultLoc = { lat: 35.6895, lng: 139.6917 };
    const timeoutId = setTimeout(() => {
      setLocation(prev => prev || defaultLoc);
    }, 5000);

    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          clearTimeout(timeoutId);
          setLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        },
        () => {
          clearTimeout(timeoutId);
          setLocation(defaultLoc);
        },
        { timeout: 10000 }
      );
    } else {
      clearTimeout(timeoutId);
      setLocation(defaultLoc);
    }
    return () => clearTimeout(timeoutId);
  }, []);

  const nextSolarEvents = useMemo(() => {
    if (!location) return null;
    const now = new Date();
    
    const today = now;
    const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);
    const dayAfter = new Date(now.getTime() + 48 * 60 * 60 * 1000);
    
    const tToday = SunCalc.getTimes(today, location.lat, location.lng);
    const tTomorrow = SunCalc.getTimes(tomorrow, location.lat, location.lng);
    const tDayAfter = SunCalc.getTimes(dayAfter, location.lat, location.lng);
    
    const mToday = SunCalc.getMoonTimes(today, location.lat, location.lng);
    const mTomorrow = SunCalc.getMoonTimes(tomorrow, location.lat, location.lng);
    const mDayAfter = SunCalc.getMoonTimes(dayAfter, location.lat, location.lng);

    const formatEvent = (time: Date) => time.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });

    const solarEvents = [
      { type: 'RISE', icon: Sunrise, time: tToday.sunrise, isTomorrow: false },
      { type: 'SET', icon: Sunset, time: tToday.sunset, isTomorrow: false },
      { type: 'RISE', icon: Sunrise, time: tTomorrow.sunrise, isTomorrow: true },
      { type: 'SET', icon: Sunset, time: tTomorrow.sunset, isTomorrow: true },
      { type: 'RISE', icon: Sunrise, time: tDayAfter.sunrise, isTomorrow: true },
      { type: 'SET', icon: Sunset, time: tDayAfter.sunset, isTomorrow: true },
    ].filter(e => e.time && e.time.getTime() > now.getTime());
    
    solarEvents.sort((a, b) => a.time.getTime() - b.time.getTime());
    
    const lunarEvents = [
      { type: 'MOONRISE', icon: Moon, time: mToday.rise, isTomorrow: false },
      { type: 'MOONSET', icon: Moon, time: mToday.set, isTomorrow: false },
      { type: 'MOONRISE', icon: Moon, time: mTomorrow.rise, isTomorrow: true },
      { type: 'MOONSET', icon: Moon, time: mTomorrow.set, isTomorrow: true },
      { type: 'MOONRISE', icon: Moon, time: mDayAfter.rise, isTomorrow: true },
      { type: 'MOONSET', icon: Moon, time: mDayAfter.set, isTomorrow: true },
    ].filter(e => e.time && e.time.getTime() > now.getTime());
    
    lunarEvents.sort((a, b) => (a.time as Date).getTime() - (b.time as Date).getTime());

    return {
      solar: solarEvents.slice(0, 2).map(e => ({ ...e, formatted: formatEvent(e.time) })),
      lunar: lunarEvents.slice(0, 2).map(e => ({ ...e, formatted: formatEvent(e.time as Date) }))
    };
  }, [location]);

  useEffect(() => {
    const unsub = realOnSnapshot(realDoc(realDb, "settings", "slideshow"), (snapshot) => {
      if (snapshot.exists()) {
        const data = snapshot.data();
        if (data.images && Array.isArray(data.images)) {
          if (data.images.length > 0 && typeof data.images[0] === 'string') {
            setRemoteImages(data.images.map((img: string) => ({ url: img, caption: "" })).filter((item: any) => item.url.trim() !== ""));
          } else {
            setRemoteImages(data.images.filter((item: any) => item.url?.trim() !== ""));
          }
        } else {
          setRemoteImages([]);
        }
      } else {
        setRemoteImages([]);
      }
    }, (error) => console.error("Slideshow onSnapshot error:", error));
    return () => unsub();
  }, []);

  const defaultImages = [
    { url: "https://drive.google.com/file/d/11hO581a9_0fyKXA7ZF9m41ASnXC5_8QM/view?usp=drive_link", caption: "『風景写真』2026年5-6月号巻頭ギャラリー\n林惣一「こころ葉」より" },
    { url: "https://drive.google.com/file/d/1HhI0C2lKh9Vbio3iIGBojlzMmt1JJm_N/view?usp=drive_link", caption: "『風景写真』2026年5-6月号巻頭ギャラリー\n林惣一「こころ葉」より" },
    { url: "https://drive.google.com/file/d/1sg9kmAVN3IRejfRM2i_LvmPbq0BfmhFy/view?usp=drive_link", caption: "『風景写真』2026年5-6月号特集ギャラリー\n「心ゆくまで夏楽園」より・佐藤尚（ツツジ）" },
    { url: "https://drive.google.com/file/d/15G4n112_3spjxi7BW7UZ9c8fYGn-fQfI/view?usp=drive_link", caption: "『風景写真』2026年5-6月号特集ギャラリー\n「心ゆくまで夏楽園」より・萩原れい子（ニッコウキスゲ）" },
    { url: "https://drive.google.com/file/d/1YXSEu5lBYg8eAoRtewyD05XoraVewIKt/view?usp=drive_link", caption: "『風景写真』2026年5-6月号特集ギャラリー\n「心ゆくまで夏楽園」より・喜多規子（ヤマボウシ）" }
  ];

  const slideshowImages = remoteImages === null || remoteImages.length === 0 ? defaultImages : remoteImages;

  useEffect(() => {
    if (slideshowImages.length === 0) return;
    const timer = setInterval(() => {
      setCurrentImageIndex((prev) => (prev + 1) % slideshowImages.length);
    }, 10000); // 10 seconds for deeper appreciation
    return () => clearInterval(timer);
  }, [slideshowImages.length]);

  return (
    <section className="relative h-screen overflow-hidden flex items-center justify-center">
      <div className="absolute inset-0 z-0 bg-stone-900">
        <AnimatePresence initial={false} mode="wait">
          {slideshowImages.length > 0 && (
            <motion.div
              key={currentImageIndex}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 2.5 }}
              className="absolute inset-0"
            >
              <motion.div 
                style={{ y }}
                className="w-full h-full"
              >
                <img 
                  src={getDirectImageUrl(slideshowImages[currentImageIndex].url)} 
                  alt="Landscape of Japan" 
                  className="w-full h-full object-cover brightness-[0.65]"
                  referrerPolicy="no-referrer"
                  onError={(e) => {
                    // Fallback to a solid color if image fails to load
                    const target = e.target as HTMLImageElement;
                    target.style.display = "none";
                  }}
                />
                
                {/* Caption Display */}
                {slideshowImages[currentImageIndex].caption && (
                  <div className="absolute bottom-6 left-0 right-0 md:left-auto md:right-12 z-20 flex justify-center md:justify-end px-4 pointer-events-none drop-shadow-md">
                    <p className="text-white text-[11px] md:text-sm font-serif leading-relaxed text-center md:text-right whitespace-pre-wrap opacity-80 max-w-[80%] md:max-w-md bg-stone-900/40 p-2 md:p-3 rounded-sm backdrop-blur-sm">
                      {slideshowImages[currentImageIndex].caption}
                    </p>
                  </div>
                )}
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      
      <div className="relative z-30 text-center px-6">
        <motion.span 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="text-emerald-200 uppercase tracking-[0.3em] text-sm font-bold mb-4 block drop-shadow-md"
        >
          The Art of Japanese Landscape
        </motion.span>
        <motion.h1 
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="text-5xl md:text-8xl font-serif text-white mb-6 leading-tight drop-shadow-lg pl-[0.2em]"
        >
          一瞬の光、<br />永遠の風景。
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
          className="text-white text-lg md:text-xl mb-10 font-medium drop-shadow-md"
        >
          {issueTitle} 好評発売中
        </motion.p>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.8 }}
          className="flex flex-col md:flex-row gap-4 justify-center items-center"
        >
          <button 
            onClick={onIssueClick}
            className="bg-white text-emerald-900 px-10 py-4 font-bold hover:bg-emerald-50 transition-colors shadow-lg w-full md:w-64"
          >
            最新号を見る
          </button>
          <button 
            onClick={onSubClick}
            className="border border-white text-white px-10 py-4 font-bold hover:bg-white/10 transition-colors backdrop-blur-sm w-full md:w-64"
          >
            定期購読のご案内
          </button>
        </motion.div>

        {/* Astro Quick Info */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.0 }}
          className="mt-6 md:mt-16 inline-flex flex-wrap items-center justify-center gap-4 md:gap-x-8 md:gap-y-4 px-4 md:px-8 py-3 md:py-4 bg-black/60 backdrop-blur-md rounded-xl md:rounded-full border border-white/20 shadow-2xl"
        >
          <Link to="/reference" className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 group hover:text-emerald-300 transition-colors">
            {nextSolarEvents && (
              <>
                {nextSolarEvents.solar.map((ev, i) => {
                  const Icon = ev.icon;
                  return (
                    <div key={`solar-${i}`} className="relative flex flex-col items-center mt-1 mb-0.5">
                      <div className="h-3.5 flex items-center justify-center w-full mb-[2px]">{ev.isTomorrow && <span className="text-[8px] font-bold text-amber-400 bg-amber-400/10 px-1 py-0.5 rounded-sm border border-amber-400/20 tracking-wider leading-none">TOMORROW</span>}</div>
                      <div className="flex items-center gap-2">
                        <Icon className="w-4 h-4 text-emerald-400" />
                        <span className="text-[9px] md:text-[10px] font-bold opacity-70 uppercase md:mr-1">{ev.type}</span>
                        <span className="text-sm font-mono text-white tracking-widest">{ev.formatted}</span>
                      </div>
                    </div>
                  );
                })}
                <div className="hidden md:flex items-center gap-6 border-l border-white/20 pl-6 ml-2">
                  {nextSolarEvents.lunar.map((ev, i) => {
                    const Icon = ev.icon;
                    return (
                      <div key={`lunar-${i}`} className="relative flex flex-col items-center mt-1 mb-0.5">
                      <div className="h-3.5 flex items-center justify-center w-full mb-[2px]">{ev.isTomorrow && <span className="text-[8px] font-bold text-amber-400 bg-amber-400/10 px-1 py-0.5 rounded-sm border border-amber-400/20 tracking-wider leading-none">TOMORROW</span>}</div>
                        <div className="flex items-center gap-2">
                          <Icon className={`w-4 h-4 text-emerald-400 ${ev.type === 'MOONSET' ? 'rotate-180' : ''}`} />
                          <span className="text-[10px] font-bold opacity-60 uppercase mr-1">{ev.type}</span>
                          <span className="text-sm font-mono text-white tracking-widest">{ev.formatted}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
            <ChevronRight className="w-4 h-4 text-white group-hover:translate-x-1 transition-transform ml-1 md:ml-0" />
          </Link>
        </motion.div>
      </div>

      <motion.div 
        animate={{ y: [0, 10, 0] }}
        transition={{ repeat: Infinity, duration: 2 }}
        className="absolute bottom-10 left-1/2 -translate-x-1/2 text-white opacity-50"
      >
        <div className="w-[1px] h-12 bg-white mx-auto mb-2"></div>
        <span className="text-[10px] uppercase tracking-widest">Scroll</span>
      </motion.div>
    </section>
  );
};

const MagazineSection = () => {
  const [issue, setIssue] = useState<LatestIssueConfig | null>(null);

  useEffect(() => {
    const unsub = realOnSnapshot(realDoc(realDb, "settings", "latest_issue"), (snapshot) => {
      if (snapshot.exists()) {
        setIssue(snapshot.data() as LatestIssueConfig);
      }
    }, (error) => console.error("MagazineSection onSnapshot error:", error));
    return () => unsub();
  }, []);

  const defaultIssue: LatestIssueConfig = {
    coverImage: "https://img16.shop-pro.jp/PA01095/035/product/191545024.png?cmsp_timestamp=20260421165639",
    title: "隔月刊『風景写真』\n2026年 5-6月号",
    description: "初夏、それは鮮やかな緑色を背に色とりどりの花々が咲き競う「花の季節」です。今号の『風景写真』では撮れ高に期待膨らむ自然園・ガーデンに焦点を当て、日本の花風景の魅力に迫ります。",
    purchaseUrl: "https://fukei-shashin.shop-pro.jp/?pid=191545024",
    price: "2200円",
    releaseDate: "2026年4月20日",
    features: [
      "心ゆくまで花楽園―初夏の自然園・ガーデンを撮る",
      "林惣一「こころ葉」／星野翔「律」",
      "チームチャンピオンズカップ2026 長野大会"
    ],
    updatedAt: null
  };
  const data = {
    coverImage: issue?.coverImage || defaultIssue.coverImage,
    title: issue?.title || defaultIssue.title,
    description: issue?.description || defaultIssue.description,
    purchaseUrl: issue?.purchaseUrl || defaultIssue.purchaseUrl,
    price: issue?.price || defaultIssue.price,
    releaseDate: issue?.releaseDate || defaultIssue.releaseDate,
    features: Array.isArray(issue?.features) && issue.features.length > 0 ? issue.features : defaultIssue.features
  };

  return (
    <section id="magazine" className="py-16 md:py-24 bg-stone-50">
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <div className="grid md:grid-cols-2 gap-12 md:gap-16 items-center">
          <motion.div 
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="relative"
          >
            <div className="absolute -top-10 -left-10 w-40 h-40 bg-emerald-100 -z-10"></div>
            <img 
              src={getDirectImageUrl(data.coverImage)} 
              alt="Magazine Cover" 
              className="w-full shadow-2xl rounded-sm"
              referrerPolicy="no-referrer"
              onError={(e) => {
                const target = e.target as HTMLImageElement;
                  target.src = "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?q=80&w=800&auto=format&fit=crop";
              }}
            />
          </motion.div>
          
          <motion.div 
            initial={{ opacity: 0, x: 50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
          >
            <span className="text-emerald-700 font-bold tracking-widest text-sm mb-4 block">LATEST ISSUE</span>
            <h2 className="text-4xl font-serif text-gray-900 mb-6 whitespace-pre-wrap">{data.title}</h2>
            <p className="text-gray-600 mb-8 leading-relaxed">
              {data.description}
            </p>
            <div className="space-y-4 mb-10">
              {data.features.filter(f => f.trim()).map((f, i) => (
                <div key={i} className="flex items-center gap-3 text-gray-700">
                  <ChevronRight className="text-emerald-600 w-4 h-4" />
                  <span>{f}</span>
                </div>
              ))}
            </div>
            <div className="flex gap-4">
              <button 
                onClick={() => window.open(data.purchaseUrl, "_blank")}
                className="bg-emerald-900 text-white px-8 py-3 rounded-sm font-bold hover:bg-emerald-800 transition-colors flex items-center gap-2"
              >
                <ShoppingBag className="w-4 h-4" />
                購入する
              </button>
              <button 
                onClick={() => {
                  window.open("https://fukei-shashin.shop-pro.jp/?mode=cate&cbid=748845&csid=0", "_blank");
                }}
                className="text-emerald-900 border border-emerald-900 px-8 py-3 rounded-sm font-bold hover:bg-emerald-50 transition-colors"
              >
                バックナンバーを見る
              </button>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
};

const ContestSection = () => {
  const [config, setConfig] = useState<any>(null);

  useEffect(() => {
    const unsub = realOnSnapshot(realDoc(realDb, "settings", "contest"), (snapshot) => {
      if (snapshot.exists()) {
        setConfig(snapshot.data() as any);
      }
    }, (error) => console.error("Contest onSnapshot error:", error));
    return () => unsub();
  }, []);

  const defaultContests = [
    { 
      title: "『風景写真』誌上フォトコンテスト", 
      deadline: "2026.05.31（2026年11-12月号）", 
      description: "賞金：最優秀作品賞 3万円他",
      url: "https://fukei-shashin.shop-pro.jp/?mode=f3",
      bannerImage: ""
    },
    { 
      title: "風景写真最高の栄誉；前田真三賞", 
      deadline: "2026.6.30（予選通過者のみ応募可）", 
      description: "受賞者には『風景写真』誌上に作品発表の機会を提供",
      url: "https://fukei-shashin.shop-pro.jp/?mode=f3",
      bannerImage: ""
    },
    { 
      title: "風景写真のレッドカーペット：風景写真祭", 
      deadline: "2026.09.08", 
      description: "富士フイルムフォトサロン東京他、各地の写真展会場に展示",
      url: "https://fukei-shashin.shop-pro.jp/?mode=f3",
      bannerImage: ""
    },
  ];

  return (
    <section id="contest" className="py-16 md:py-24 bg-emerald-900 text-white overflow-hidden relative">
      <div className="absolute top-0 right-0 w-1/3 h-full opacity-10 pointer-events-none">
        <Trophy className="w-full h-full" />
      </div>
      
      <div className="max-w-7xl mx-auto px-4 md:px-6 relative z-10">
        <div className="text-center mb-12 md:mb-16">
          <motion.h2 
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-3xl md:text-4xl font-serif mb-4"
          >
            コンテスト、写真展参加作品募集中
          </motion.h2>
          <p className="text-emerald-200 max-w-2xl mx-auto">
            あなたの視点が、誰かの感動に。風景写真出版では、四季折々の美しさを捉えた作品を募集しています。
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-8">
          {(config?.contests || defaultContests).map((contest: any, i: number) => (
            <motion.div 
              key={i}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1 }}
              className="bg-white/5 border border-white/10 overflow-hidden hover:bg-white/10 transition-colors group cursor-pointer flex flex-col h-full"
              onClick={() => window.open(contest.url, "_blank")}
            >
              {contest.bannerImage ? (
                <div className="aspect-video w-full overflow-hidden">
                  <img src={getDirectImageUrl(contest.bannerImage)} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" alt={contest.title} />
                </div>
              ) : (
                <div className="p-8 pb-0">
                  <Trophy className="text-emerald-400 w-8 h-8 group-hover:scale-110 transition-transform" />
                </div>
              )}
              
              <div className="p-8 flex flex-col flex-grow">
                <h3 className="text-xl font-bold mb-4">{contest.title}</h3>
                <div className="space-y-2 text-sm text-emerald-200 mb-6 flex-grow">
                  <p className="font-mono text-xs mb-2 block border-b border-white/10 pb-2">締切：{contest.deadline}</p>
                  <p className="leading-relaxed">{contest.description}</p>
                </div>
                <button className="text-white font-bold flex items-center gap-2 group-hover:gap-4 transition-all mt-auto">
                  募集要項を見る <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};

const GallerySection = () => {
  const [galleryItems, setGalleryItems] = useState<GalleryItem[]>([]);

  useEffect(() => {
    const unsub = realOnSnapshot(realDoc(realDb, "settings", "gallery"), (snapshot) => {
      if (snapshot.exists()) {
        const data = snapshot.data();
        if (data.items && Array.isArray(data.items)) {
          setGalleryItems(data.items);
        }
      }
    }, (error) => {
      console.error("Gallery onSnapshot error:", error);
    });
    return () => unsub();
  }, []);

  const defaultItems = [
    { src: "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?q=80&w=800&auto=format&fit=crop", labelJP: "春", labelEN: "SPRING" },
    { src: "https://images.unsplash.com/photo-1545569341-9eb8b30979d9?q=80&w=800&auto=format&fit=crop", labelJP: "夏", labelEN: "SUMMER" },
    { src: "https://images.unsplash.com/photo-1493780474015-ba834ff0ce2f?q=80&w=800&auto=format&fit=crop", labelJP: "秋", labelEN: "AUTUMN" }, 
    { src: "https://images.unsplash.com/photo-1475924156731-498ff7931435?q=80&w=800&auto=format&fit=crop", labelJP: "冬", labelEN: "WINTER" },
    { src: "https://images.unsplash.com/photo-1524230507669-5ff97982bb5e?q=80&w=800&auto=format&fit=crop", labelJP: "桜", labelEN: "CHERRY BLOSSOM" },
    { src: "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?q=80&w=800&auto=format&fit=crop", labelJP: "紅", labelEN: "AUTUMN LEAVES" },
    { src: "https://images.unsplash.com/photo-1526481280693-3bfa7561eca0?q=80&w=800&auto=format&fit=crop", labelJP: "里", labelEN: "SATOYAMA" },
    { src: "https://images.unsplash.com/photo-1439066615861-d1af74d74000?q=80&w=800&auto=format&fit=crop", labelJP: "水", labelEN: "WATER" },
  ];

  const items = galleryItems.length > 0 ? galleryItems : defaultItems;

  return (
    <section id="gallery" className="py-16 md:py-24">
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <div className="flex justify-between items-end mb-8 md:mb-12">
          <div>
            <h2 className="text-3xl md:text-4xl font-serif text-gray-900 mb-2">オンライン・ギャラリー</h2>
            <p className="text-gray-500 text-sm md:text-base font-medium tracking-wide">A curated gallery of Japan's most breathtaking landscapes.</p>
          </div>
          <button className="hidden md:block text-emerald-900 font-bold border-b-2 border-emerald-900 pb-1 hover:opacity-70 transition-opacity">
            すべて見る
          </button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {items.map((item, i) => (
            <motion.div 
              key={i}
              initial={{ opacity: 0, scale: 0.95 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.05 }}
              className="aspect-square overflow-hidden group cursor-pointer relative bg-gray-100"
            >
              <img 
                src={`${getDirectImageUrl(item.src)}?t=${i}`} 
                alt={item.labelJP} 
                className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700"
                referrerPolicy="no-referrer"
                onError={(e) => {
                  const target = e.target as HTMLImageElement;
                  target.src = "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?q=80&w=800&auto=format&fit=crop";
                }}
              />
              <div className="absolute inset-0 bg-emerald-900/40 opacity-0 group-hover:opacity-100 transition-opacity duration-500 flex items-center justify-center backdrop-blur-[2px]">
                <div className="flex flex-col items-center text-center px-4">
                  <span className="text-white text-6xl md:text-8xl font-serif font-bold scale-50 group-hover:scale-100 transition-transform duration-500 drop-shadow-2xl">
                    {item.labelJP}
                  </span>
                  <span className="text-white text-[10px] md:text-xs tracking-[0.4em] mt-2 opacity-0 group-hover:opacity-100 transition-opacity duration-700 delay-100 uppercase font-bold">
                    {item.labelEN}
                  </span>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};

const ShopSection = () => {
  return (
    <section id="shop" className="py-16 md:py-24 bg-stone-100">
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <div className="text-center mb-12 md:mb-16">
          <h2 className="text-3xl md:text-4xl font-serif text-gray-900 mb-4">公式ショップ</h2>
          <p className="text-gray-500 text-sm md:text-base">あなたの日常に、風景の彩りを。</p>
        </div>

        <div className="grid md:grid-cols-4 gap-8">
          {[
            { name: "2026年 壁掛けカレンダー", price: "¥2,200", img: "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?q=80&w=400&auto=format&fit=crop" },
            { name: "卓上カレンダー：日本の四季", price: "¥1,320", img: "https://images.unsplash.com/photo-1545569341-9eb8b30979d9?q=80&w=400&auto=format&fit=crop" },
            { name: "写真集：光の記憶", price: "¥3,850", img: "https://images.unsplash.com/photo-1528164344705-47542687000d?q=80&w=400&auto=format&fit=crop" },
            { name: "風景写真 特製ポストカード", price: "¥880", img: "https://images.unsplash.com/photo-1545569341-9eb8b30979d9?q=80&w=400&auto=format&fit=crop" },
          ].map((item, i) => (
            <motion.div 
              key={i}
              whileHover={{ y: -10 }}
              className="bg-white p-4 rounded-sm shadow-sm"
            >
              <img 
                src={item.img} 
                alt={item.name} 
                className="w-full aspect-[3/4] object-cover mb-4 rounded-sm"
              />
              <h3 className="font-bold text-gray-900 mb-1">{item.name}</h3>
              <p className="text-emerald-700 font-bold mb-4">{item.price}</p>
              <button className="w-full border border-gray-200 py-2 text-sm font-bold hover:bg-gray-50 transition-colors">
                カートに入れる
              </button>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};

const ContactSection = () => {
  return (
    <section id="contact" className="py-16 md:py-24 bg-white">
      <div className="max-w-3xl mx-auto px-4 md:px-6 text-center">
        <h2 className="text-3xl md:text-4xl font-serif text-gray-900 mb-6">お問い合わせ</h2>
        <p className="text-gray-500 mb-12">
          雑誌の購読、広告掲載、作品の投稿などに関するお問い合わせはこちらからお願いいたします。
        </p>
        <form className="space-y-6 text-left">
          <div className="grid md:grid-cols-2 gap-6">
            <div className="space-y-2">
              <label className="text-sm font-bold text-gray-700">お名前</label>
              <input type="text" className="w-full border-b border-gray-300 py-2 focus:border-emerald-900 outline-none transition-colors" placeholder="山田 太郎" />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-bold text-gray-700">メールアドレス</label>
              <input type="email" className="w-full border-b border-gray-300 py-2 focus:border-emerald-900 outline-none transition-colors" placeholder="example@mail.com" />
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-bold text-gray-700">お問い合わせ内容</label>
            <textarea rows={4} className="w-full border-b border-gray-300 py-2 focus:border-emerald-900 outline-none transition-colors resize-none" placeholder="メッセージを入力してください"></textarea>
          </div>
          <button className="w-full bg-emerald-900 text-white py-4 font-bold hover:bg-emerald-800 transition-colors shadow-lg">
            送信する
          </button>
        </form>
      </div>
    </section>
  );
};

const FooterLogo = () => {
  return (
    <a href="/about/index.html" className="flex items-center mb-6" aria-label="風景写真PUBLISHINGについて">
      <LogoLandscape variant="bright" className="h-12 md:h-16 w-auto" />
    </a>
  );
};

const Footer = ({ onSecretPortal, onOpenSubscription }: { onSecretPortal: () => void, onOpenSubscription: () => void }) => {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [isSubscribing, setIsSubscribing] = useState(false);

  const handleSubscribe = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || isSubscribing) return;
    
    setIsSubscribing(true);
    try {
      await realSetDoc(realDoc(realDb, "subscribers", email.replace(/\./g, '_')), {
        email,
        createdAt: realServerTimestamp()
      });
      alert('ニュースレターに登録しました。ありがとうございます！');
      setEmail("");
    } catch (err) {
      console.error(err);
      handleFirestoreError(err, 'create', `subscribers/${email.replace(/\./g, '_')}`);
    } finally {
      setIsSubscribing(false);
    }
  };

  const handleSecretDoor = (e: React.MouseEvent) => {
    if (e.altKey || e.metaKey) {
      onSecretPortal();
    }
  };

  return (
    <footer className="bg-emerald-950 text-white py-16 md:py-20">
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-12 mb-16">
          <div className="col-span-1 md:col-span-1">
            <FooterLogo />
            <p className="text-emerald-200/60 text-sm leading-relaxed mb-6">
              風景写真出版は、日本の美しい風景を次世代に伝え、写真文化の発展に寄与することを目指しています。
            </p>
            <div className="flex gap-4">
              <Instagram className="w-5 h-5 cursor-pointer hover:text-emerald-400 transition-colors" />
              <Facebook className="w-5 h-5 cursor-pointer hover:text-emerald-400 transition-colors" />
              <button className="w-5 h-5 cursor-pointer hover:text-emerald-400 transition-colors" aria-label="X">
                <svg viewBox="0 0 24 24" className="w-full h-full fill-current" xmlns="http://www.w3.org/2000/svg">
                  <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
                </svg>
              </button>
            </div>
          </div>

          <div>
            <h4 className="font-bold mb-6 text-emerald-400">コンテンツ</h4>
            <ul className="space-y-4 text-sm text-emerald-200/60">
              <li><a href="/policy/index.html" className="hover:text-white transition-colors">雑誌・書籍</a></li>
              <li><Link to="/blog" className="hover:text-white transition-colors">お知らせ・ブログ</Link></li>
              <li>
                <a href="/#contest" onClick={(e) => {
                  if (window.location.pathname === '/') {
                    e.preventDefault();
                    document.getElementById('contest')?.scrollIntoView({ behavior: 'smooth' });
                  }
                }} className="hover:text-white transition-colors">フォトコンテスト</a>
              </li>
            </ul>
          </div>

          <div>
            <h4 className="font-bold mb-6 text-emerald-400">サポート</h4>
            <ul className="space-y-4 text-sm text-emerald-200/60">
              <li><button onClick={onOpenSubscription} className="hover:text-white transition-colors">定期購読について</button></li>
              <li>
                <a href="/#contact" onClick={(e) => {
                  if (window.location.pathname === '/') {
                    e.preventDefault();
                    document.getElementById('contact')?.scrollIntoView({ behavior: 'smooth' });
                  }
                }} className="hover:text-white transition-colors">お問い合わせ</a>
              </li>
              <li><a href="/policy/index.html" className="hover:text-white transition-colors">プライバシーポリシー</a></li>
              <li><a href="/about/index.html" className="hover:text-white transition-colors">風景写真出版について</a></li>
            </ul>
          </div>

          <div>
            <h4 className="font-bold mb-6 text-emerald-400">ニュースレター</h4>
            <p className="text-sm text-emerald-200/60 mb-4">最新のコンテスト情報や出版案内をお届けします。</p>
            <form className="flex" onSubmit={handleSubscribe}>
              <input 
                type="email" 
                placeholder="Email address" 
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="bg-white/10 border-none px-4 py-2 text-sm w-full focus:ring-1 focus:ring-emerald-400 outline-none"
              />
              <button 
                type="submit"
                disabled={isSubscribing}
                className="bg-emerald-600 px-4 py-2 hover:bg-emerald-500 transition-colors disabled:opacity-50"
              >
                {isSubscribing ? <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" /> : <ChevronRight className="w-4 h-4" />}
              </button>
            </form>
          </div>
        </div>

        <div className="border-t border-white/10 pt-8 flex flex-col md:flex-row justify-between items-center gap-4 text-[10px] text-emerald-200/40 uppercase tracking-[0.2em]">
          <div className="flex items-center gap-4">
            <p 
              className="cursor-default select-none transition-colors hover:text-emerald-400"
              onClick={handleSecretDoor}
            >
              © 2026 FUKEI SHASHIN SHUPPAN. ALL RIGHTS RESERVED.
            </p>
            <Link to="/login" className="hover:text-emerald-400 transition-colors hidden md:block">
              ADMIN LOGIN
            </Link>
          </div>
          <div className="flex gap-4 items-center">
            <Link to="/login" className="hover:text-emerald-400 transition-colors md:hidden">
              ADMIN LOGIN
            </Link>
            <span className="hover:text-emerald-400 transition-colors cursor-default hidden md:inline">Designed for the Beauty of Nature</span>
          </div>
        </div>
      </div>
    </footer>
  );
};

const NewsSection = () => {
  const [posts, setPosts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/news/exblog')
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data) && data.length > 0) {
          setPosts(data);
        }
      })
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, []);

  const displayPosts = posts.length > 0 ? posts : blogPosts.slice(0, 5);

  return (
    <section id="news" className="py-16 md:py-24 bg-white border-b border-gray-100">
      <div className="max-w-4xl mx-auto px-4 md:px-6">
        <div className="flex justify-between items-end mb-8 md:mb-12">
          <div>
            <span className="text-emerald-700 font-bold tracking-widest text-[10px] md:text-xs mb-2 block uppercase">News & Updates</span>
            <h2 className="text-3xl md:text-4xl font-serif text-gray-900">最新情報</h2>
          </div>
          <a href="https://fukeinews.exblog.jp/" target="_blank" rel="noopener noreferrer" className="text-emerald-900 font-bold flex items-center gap-2 hover:opacity-70 transition-opacity">
            すべて見る <ChevronRight className="w-4 h-4" />
          </a>
        </div>

        {loading ? (
          <div className="py-12 flex justify-center"><div className="animate-spin h-6 w-6 border-2 border-emerald-600 border-t-transparent rounded-full" /></div>
        ) : (
          <div className="border-t border-stone-200">
            {displayPosts.map((post) => {
              const url = post.link || `/blog/${post.id}`;
              const isExternal = url.startsWith('http');
              const linkContent = (
                <div className="flex flex-col md:flex-row md:items-center gap-2 md:gap-6 px-2">
                  <div className="flex text-xs text-gray-400 w-32 shrink-0">
                    <span className="font-mono">{post.date}</span>
                  </div>
                  {post.category ? (
                    <div className="w-24 shrink-0">
                      <span className="bg-emerald-50 text-emerald-800 border border-emerald-100 text-[10px] px-2 py-1 font-bold rounded-sm uppercase tracking-wider block text-center">
                        {post.category}
                      </span>
                    </div>
                  ) : <div className="w-0 shrink-0 md:w-0" />}
                  <h3 className="text-sm md:text-base font-bold text-gray-900 group-hover:text-emerald-700 transition-colors line-clamp-2 leading-snug">
                    {post.title}
                  </h3>
                </div>
              );

              return isExternal ? (
                <a href={url} target="_blank" rel="noopener noreferrer" key={post.id || url} className="group block border-b border-stone-200 py-4 hover:bg-stone-50 transition-colors">
                  {linkContent}
                </a>
              ) : (
                <Link to={url} key={post.id} className="group block border-b border-stone-200 py-4 hover:bg-stone-50 transition-colors">
                  {linkContent}
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
};

const BlogListPage = () => {
  const [posts, setPosts] = useState<DBPost[]>([]);
  const { isAdmin } = useAuth();

  useEffect(() => {
    window.scrollTo(0, 0);
    const q = realQuery(realCollection(realDb, "posts"), realOrderBy("createdAt", "desc"));
    const unsubscribe = realOnSnapshot(q, (snapshot) => {
      setPosts(snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() } as DBPost)));
    }, (error) => console.error("Posts onSnapshot error:", error));
    return () => unsubscribe();
  }, []);

  const displayPosts = posts.length > 0 ? posts : blogPosts;

  return (
    <div className="pt-32 pb-24 bg-stone-50 min-h-screen">
      <div className="max-w-5xl mx-auto px-6">
        {isAdmin && (
          <div className="mb-8 flex justify-end">
            <Link to="/admin" className="bg-emerald-900 text-white px-6 py-2 rounded-sm font-bold flex items-center gap-2 hover:bg-emerald-800 transition-colors">
              <LayoutDashboard className="w-4 h-4" />
              管理画面へ
            </Link>
          </div>
        )}
        <div className="mb-16 text-center">
          <span className="text-emerald-700 font-bold tracking-[0.3em] text-sm mb-4 block uppercase leading-relaxed font-sans">
            風景写真出版からのお知らせ　風景多彩
          </span>
          <h1 className="text-7xl md:text-8xl font-serif text-emerald-950 mb-8 tracking-tight drop-shadow-sm">
            風景多彩
          </h1>
          <div className="w-16 h-1 bg-emerald-900 mx-auto mb-8"></div>
          <p className="text-gray-500 max-w-2xl mx-auto leading-relaxed">
            イベント情報、雑誌・書籍の発売案内など、風景写真出版の最新情報をお届けします。
          </p>
        </div>

        <div className="space-y-12">
          {displayPosts.map((post) => (
            <motion.div 
              key={post.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-white p-6 md:p-8 rounded-sm shadow-sm flex flex-col md:flex-row gap-8 items-center"
            >
              <div className="w-full md:w-1/3 aspect-[4/3] rounded-sm overflow-hidden flex-shrink-0">
                <img src={getDirectImageUrl(post.image)} alt={post.title} className="w-full h-full object-cover" />
              </div>
              <div className="flex-grow">
                <div className="flex items-center gap-4 mb-4">
                  <span className="bg-stone-100 text-emerald-800 text-[10px] px-3 py-1 font-bold rounded-full border border-emerald-100 uppercase tracking-widest">
                    {post.category}
                  </span>
                  <span className="text-xs text-gray-400 font-mono">{post.date}</span>
                </div>
                <h2 className="text-2xl font-bold text-emerald-950 mb-4 leading-tight">{post.title}</h2>
                <p className="text-gray-600 mb-6 line-clamp-2">
                  {post.excerpt}
                </p>
                <Link to={`/blog/${post.id}`} className="inline-flex items-center gap-2 text-emerald-900 font-bold hover:gap-3 transition-all border-b border-emerald-900/20 pb-1">
                  詳細を読む <ChevronRight className="w-4 h-4" />
                </Link>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
};

const BlogPostPage = () => {
  const { id } = useParams();
  const [post, setPost] = useState<DBPost | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    window.scrollTo(0, 0);
    const fetchPost = async () => {
      if (!id) return;
      
      // Try DB first
      const docRef = doc(db, "posts", id);
      let docSnap;
      try {
        docSnap = null;
      } catch (err) {
        
      }
      
      if (docSnap && docSnap.exists()) {
        const data = docSnap.data() as DBPost;
        setPost({ id: docSnap.id, ...data });
        
        // Increment views
        try { } catch (e) {
          console.error("View count update failed:", e);
          
        }
      } else {
        // Fallback to static
        const staticPost = blogPosts.find(p => p.id === id);
        if (staticPost) {
          setPost({ ...staticPost, views: 0, authorId: 'system', createdAt: null, updatedAt: null });
        }
      }
      setLoading(false);
    };

    fetchPost();
  }, [id]);

  if (loading) {
    return (
      <div className="pt-32 pb-24 bg-white min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-900"></div>
      </div>
    );
  }

  if (!post) {
    return (
      <div className="pt-32 pb-24 bg-stone-50 min-h-screen flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-4xl font-serif mb-4 text-emerald-950">記事が見つかりません</h1>
          <Link to="/blog" className="text-emerald-900 font-bold border-b border-emerald-900">ブログ一覧に戻る</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="pt-32 pb-24 bg-white min-h-screen font-sans">
      <div className="max-w-3xl mx-auto px-6">
        <Link to="/blog" className="inline-flex items-center gap-2 text-emerald-900 font-bold mb-12 hover:-translate-x-1 transition-transform">
          <ArrowLeft className="w-4 h-4" />
          一覧に戻る
        </Link>
        
        <div className="mb-12">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-4">
              <span className="bg-emerald-50 text-emerald-700 text-px px-4 py-1 font-bold rounded-full border border-emerald-100 uppercase tracking-widest">
                {post.category}
              </span>
              <div className="flex items-center gap-1 text-xs text-gray-400">
                <Clock className="w-3 h-3" />
                <span>{post.date}</span>
              </div>
            </div>
            <div className="flex items-center gap-2 text-xs text-gray-400 font-mono">
              <Eye className="w-3 h-3" />
              <span>{post.views} views</span>
            </div>
          </div>
          <h1 className="text-4xl md:text-5xl font-serif text-emerald-950 mb-8 leading-tight">{post.title}</h1>
          <div className="aspect-[16/9] rounded-sm overflow-hidden mb-12 shadow-xl">
            <img src={getDirectImageUrl(post.image)} alt={post.title} className="w-full h-full object-cover" />
          </div>
        </div>

        <div className="prose prose-emerald lg:prose-xl max-w-none text-gray-700 mb-16 leading-relaxed">
          <Markdown>{post.content}</Markdown>
        </div>
        
        <div className="mt-16 pt-8 border-t border-stone-100 flex justify-between items-center">
          <div className="flex items-center gap-4">
            <Tag className="w-4 h-4 text-emerald-600" />
            <span className="text-sm font-medium text-gray-500">風景写真出版, ニュース, {post.category}</span>
          </div>
          <div className="flex gap-4">
            <Instagram className="w-5 h-5 text-gray-400 cursor-pointer hover:text-emerald-600" />
            <Facebook className="w-5 h-5 text-gray-400 cursor-pointer hover:text-emerald-600" />
            <Twitter className="w-5 h-5 text-gray-400 cursor-pointer hover:text-emerald-600" />
          </div>
        </div>
      </div>
    </div>
  );
};

/**
 * Admin Components
 */

const AdminLogin = () => {
  const { user, isAdmin, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && isAdmin) {
      navigate('/admin');
    }
  }, [isAdmin, loading, navigate]);

  if (loading) return null;

  return (
    <div className="min-h-screen bg-stone-100 flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-white p-12 rounded-sm shadow-xl text-center">
        <LayoutDashboard className="w-16 h-16 text-emerald-900 mx-auto mb-6" />
        <h1 className="text-2xl font-serif text-emerald-950 mb-4">管理画面へログイン</h1>
        <p className="text-gray-500 mb-8 text-sm">風景多彩のブログ記事を管理・分析するための専用ページです。</p>
        
        {user && !isAdmin ? (
          <div className="bg-red-50 text-red-700 p-4 rounded-sm text-sm mb-6">
            管理者権限がありません。別のアカウントでログインしてください。
          </div>
        ) : null}

        <button 
          onClick={signInWithGoogle}
          className="w-full flex items-center justify-center gap-3 bg-white border border-gray-200 py-3 px-4 rounded-sm font-bold text-gray-700 hover:bg-gray-50 transition-colors"
        >
          <img src="https://www.google.com/favicon.ico" className="w-5 h-5" alt="Google" />
          Googleでログイン
        </button>
      </div>
    </div>
  );
};

const AdminDashboard = () => {
  const { user, isAdmin, loading } = useAuth();
  const [posts, setPosts] = useState<DBPost[]>([]);
  const [isMigrating, setIsMigrating] = useState(false);
  const [slideshowImages, setSlideshowImages] = useState<SlideshowImage[]>([]);
  const [isSavingSlideshow, setIsSavingSlideshow] = useState(false);
  const [galleryItems, setGalleryItems] = useState<GalleryItem[]>([]);
  const [isSavingGallery, setIsSavingGallery] = useState(false);
  const defaultIssue: LatestIssueConfig = {
    coverImage: "https://img16.shop-pro.jp/PA01095/035/product/191545024.png?cmsp_timestamp=20260421165639",
    title: "隔月刊『風景写真』\n2026年 5-6月号",
    description: "初夏、それは鮮やかな緑色を背に色とりどりの花々が咲き競う「花の季節」です。今号の『風景写真』では撮れ高に期待膨らむ自然園・ガーデンに焦点を当て、日本の花風景の魅力に迫ります。",
    purchaseUrl: "https://fukei-shashin.shop-pro.jp/?pid=191545024",
    price: "¥2,200",
    releaseDate: "2026年4月20日",
    features: ["心ゆくまで花楽園―初夏の自然園・ガーデンを撮る", "林惣一「こころ葉」／星野翔「律」", "チームチャンピオンズカップ2026 長野大会"],
    updatedAt: null
  };

  const [latestIssue, setLatestIssue] = useState<LatestIssueConfig>(defaultIssue);
  const [isSavingIssue, setIsSavingIssue] = useState(false);
  
  const [contestConfig, setContestConfig] = useState({
    contests: [
      { title: "『風景写真』誌上フォトコンテスト", deadline: "2026.05.31（2026年11-12月号）", description: "賞金：最優秀作品賞 3万円他", url: "https://fukei-shashin.shop-pro.jp/?mode=f3", bannerImage: "" },
      { title: "風景写真最高の栄誉；前田真三賞", deadline: "2026.6.30（予選通過者のみ応募可）", description: "受賞者には『風景写真』誌上に作品発表の機会を提供", url: "https://fukei-shashin.shop-pro.jp/?mode=f3", bannerImage: "" },
      { title: "風景写真のレッドカーペット：風景写真祭", deadline: "2026.09.08", description: "富士フイルムフォトサロン東京他、各地の写真展会場に展示", url: "https://fukei-shashin.shop-pro.jp/?mode=f3", bannerImage: "" }
    ]
  });
  const [isSavingContest, setIsSavingContest] = useState(false);
  
  const [generalConfig, setGeneralConfig] = useState({
    refLocation: "東京"
  });
  const [isSavingGeneral, setIsSavingGeneral] = useState(false);

  const [subscribers, setSubscribers] = useState<{email: string, id: string}[]>([]);

  const [activeTab, setActiveTab] = useState<"posts" | "slideshow" | "seasonalNews" | "gallery" | "issue" | "contest" | "general" | "newsletter">("posts");
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && !isAdmin) navigate('/login');
    
    if (isAdmin) {
      const q = realQuery(realCollection(realDb, "posts"), realOrderBy("createdAt", "desc"));
      const unsubscribePosts = realOnSnapshot(q, (snapshot) => {
        setPosts(snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() } as DBPost)));
      }, (error) => console.error("Admin Posts onSnapshot error:", error));

      const unsubscribeSubscribers = realOnSnapshot(realCollection(realDb, "subscribers"), (snapshot) => {
        setSubscribers(snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() } as any)));
      }, (error) => console.error("Admin Subscribers onSnapshot error:", error));

      const unsubscribeSlideshow = realOnSnapshot(realDoc(realDb, "settings", "slideshow"), (snapshot) => {
        if (snapshot.exists()) {
          const config = snapshot.data() as SlideshowConfig;
          if (config.images && config.images.length > 0) {
            if (typeof config.images[0] === 'string') {
              setSlideshowImages((config.images as string[]).map(url => ({ url, caption: '' })));
            } else {
              setSlideshowImages(config.images as SlideshowImage[]);
            }
          } else {
            setSlideshowImages([]);
          }
        } else {
          setSlideshowImages([]);
        }
      }, (error) => console.error("Admin Slideshow onSnapshot error:", error));

      const unsubscribeGallery = realOnSnapshot(realDoc(realDb, "settings", "gallery"), (snapshot) => {
        if (snapshot.exists()) {
          setGalleryItems((snapshot.data() as GalleryConfig).items || []);
        }
      }, (error) => console.error("Admin Gallery onSnapshot error:", error));

      const unsubscribeIssue = realOnSnapshot(realDoc(realDb, "settings", "latest_issue"), (snapshot) => {
        if (snapshot.exists()) {
          const fetched = snapshot.data() as LatestIssueConfig;
          setLatestIssue({
            ...defaultIssue,
            ...fetched,
            features: fetched.features?.length ? [...fetched.features, "", "", ""].slice(0, 3) : defaultIssue.features
          });
        }
      }, (error) => console.error("Admin Issue onSnapshot error:", error));
      
      const unsubscribeContest = realOnSnapshot(realDoc(realDb, "settings", "contest"), (snapshot) => {
        if (snapshot.exists()) {
          const data = snapshot.data();
          setContestConfig(prev => ({ ...prev, ...data }));
        }
      }, (error) => console.error("Admin Contest onSnapshot error:", error));
      
      const unsubscribeGeneral = realOnSnapshot(realDoc(realDb, "settings", "general"), (snapshot) => {
        if (snapshot.exists()) {
          setGeneralConfig(snapshot.data() as any);
        }
      }, (error) => console.error("Admin General onSnapshot error:", error));

      return () => {
        unsubscribePosts();
        unsubscribeSubscribers();
        unsubscribeSlideshow();
        unsubscribeGallery();
        unsubscribeIssue();
        unsubscribeContest();
        unsubscribeGeneral();
      };
    }
  }, [isAdmin, loading, navigate]);

  const handleUpdateSlideshow = async () => {
    setIsSavingSlideshow(true);
    try {
      await realSetDoc(realDoc(realDb, "settings", "slideshow"), { 
        images: slideshowImages.filter(img => img.url.trim() !== ""), 
        updatedAt: realServerTimestamp() 
      });
      alert('スライドショー設定を更新しました。');
    } catch (err) {
      console.error(err);
      alert('エラーが発生しました: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSavingSlideshow(false);
    }
  };

  const handleUpdateIssue = async () => {
    setIsSavingIssue(true);
    try {
      await realSetDoc(realDoc(realDb, "settings", "latest_issue"), {
        ...latestIssue,
        updatedAt: realServerTimestamp()
      });
      alert('最新号情報を更新しました。');
    } catch (err) {
      console.error(err);
      alert('エラーが発生しました: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSavingIssue(false);
    }
  };

  const handleUpdateContest = async () => {
    setIsSavingContest(true);
    try {
      await realSetDoc(realDoc(realDb, "settings", "contest"), {
        ...contestConfig,
        updatedAt: realServerTimestamp()
      });
      alert('コンテスト情報を更新しました。');
    } catch (err) {
      console.error(err);
      alert('エラーが発生しました: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSavingContest(false);
    }
  };
  
  const handleUpdateGeneral = async () => {
    setIsSavingGeneral(true);
    try {
      await realSetDoc(realDoc(realDb, "settings", "general"), {
        ...generalConfig,
        updatedAt: realServerTimestamp()
      });
      alert('一般設定を更新しました。');
    } catch (err) {
      console.error(err);
      alert('エラーが発生しました: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSavingGeneral(false);
    }
  };

  const handleUpdateGallery = async () => {
    setIsSavingGallery(true);
    try {
      await realSetDoc(realDoc(realDb, "settings", "gallery"), {
        items: galleryItems,
        updatedAt: realServerTimestamp()
      });
      alert('ギャラリー設定を更新しました。');
    } catch (err) {
      console.error(err);
      alert('エラーが発生しました: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsSavingGallery(false);
    }
  };

  const handleMigrate = async () => {
    if (!confirm('既存のサンプルデータをFirestoreに移行しますか？')) return;
    setIsMigrating(true);
    for (const post of blogPosts) {
      const { id, ...data } = post;
      await realSetDoc(realDoc(realDb, "posts", id), {
        ...data,
        createdAt: realServerTimestamp()
      });
    }
    setIsMigrating(false);
    alert('移行が完了しました。');
  };

  const handleDelete = async (id: string) => {
    if (!confirm('この記事を削除してもよろしいですか？')) return;
    try {
      await realDeleteDoc(realDoc(realDb, "posts", id));
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteSubscriber = async (id: string) => {
    if (!confirm('この購読者のメールアドレスを削除してもよろしいですか？')) return;
    try {
      await realDeleteDoc(realDoc(realDb, "subscribers", id));
    } catch (err) {
      console.error(err);
    }
  };

  if (loading || !isAdmin) return <div className="h-screen flex items-center justify-center font-serif text-emerald-900">認証中...</div>;

  const totalViews = posts.reduce((acc, curr) => acc + (curr.views || 0), 0);

  return (
    <div className="min-h-screen bg-stone-50 font-sans">
      <nav className="bg-emerald-950 text-white py-4 px-8 flex justify-between items-center sticky top-0 z-50">
        <div className="flex items-center gap-4">
          <LayoutDashboard className="w-6 h-6 text-emerald-400" />
          <h1 className="text-xl font-serif">風景多彩 管理画面</h1>
        </div>
        <div className="flex items-center gap-6">
          <span className="text-xs text-emerald-200/60 hidden md:block">{user?.email}</span>
          <button onClick={() => navigate('/')} className="p-2 hover:bg-white/10 rounded-full transition-colors" title="サイトに戻る">
            <LogOut className="w-5 h-5" />
          </button>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto p-4 md:p-8">
        {/* Stats Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 md:gap-6 mb-12">
          <div className="bg-white p-6 rounded-sm shadow-sm border-l-4 border-emerald-600">
            <div className="flex items-center gap-4 text-emerald-600 mb-2">
              <FileText className="w-5 h-5" />
              <span className="text-xs font-bold uppercase tracking-wider">Total Posts</span>
            </div>
            <p className="text-4xl font-serif text-emerald-950">{posts.length}</p>
          </div>
          <div className="bg-white p-6 rounded-sm shadow-sm border-l-4 border-emerald-400">
            <div className="flex items-center gap-4 text-emerald-600 mb-2">
              <BarChart3 className="w-5 h-5" />
              <span className="text-xs font-bold uppercase tracking-wider">Total Views</span>
            </div>
            <p className="text-4xl font-serif text-emerald-950">{totalViews.toLocaleString()}</p>
          </div>
          <div className="bg-white p-6 rounded-sm shadow-sm border-l-4 border-emerald-200">
            <div className="flex items-center gap-4 text-emerald-600 mb-2">
              <Trophy className="w-5 h-5" />
              <span className="text-xs font-bold uppercase tracking-wider">Top Engagement</span>
            </div>
            <p className="text-4xl font-serif text-emerald-950">
              {posts.length > 0 ? posts.sort((a,b) => b.views - a.views)[0].category : '-'}
            </p>
          </div>
        </div>

        <div className="flex gap-8 border-b border-stone-200 mb-8 overflow-x-auto whitespace-nowrap">
          <button 
            onClick={() => setActiveTab("posts")}
            className={`pb-4 text-sm font-bold tracking-widest uppercase transition-colors relative ${activeTab === "posts" ? "text-emerald-900" : "text-stone-400 hover:text-stone-600"}`}
          >
            Blog Posts
            {activeTab === "posts" && <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-900" />}
          </button>
          <button 
            onClick={() => setActiveTab("slideshow")}
            className={`pb-4 text-sm font-bold tracking-widest uppercase transition-colors relative ${activeTab === "slideshow" ? "text-emerald-900" : "text-stone-400 hover:text-stone-600"}`}
          >
            Slideshow
            {activeTab === "slideshow" && <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-900" />}
          </button>
          <button 
            onClick={() => setActiveTab("seasonalNews")}
            className={`pb-4 text-sm font-bold tracking-widest uppercase transition-colors relative ${activeTab === "seasonalNews" ? "text-emerald-900" : "text-stone-400 hover:text-stone-600"}`}
          >
            旬撮ニュース / Archive
            {activeTab === "seasonalNews" && <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-900" />}
          </button>
{/*
          <button 
            onClick={() => setActiveTab("gallery")}
            className={`pb-4 text-sm font-bold tracking-widest uppercase transition-colors relative ${activeTab === "gallery" ? "text-emerald-900" : "text-stone-400 hover:text-stone-600"}`}
          >
            Gallery
            {activeTab === "gallery" && <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-900" />}
          </button>
*/}
          <button 
            onClick={() => setActiveTab("issue")}
            className={`pb-4 text-sm font-bold tracking-widest uppercase transition-colors relative ${activeTab === "issue" ? "text-emerald-900" : "text-stone-400 hover:text-stone-600"}`}
          >
            Issue
            {activeTab === "issue" && <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-900" />}
          </button>
          <button 
            onClick={() => setActiveTab("contest")}
            className={`pb-4 text-sm font-bold tracking-widest uppercase transition-colors relative ${activeTab === "contest" ? "text-emerald-900" : "text-stone-400 hover:text-stone-600"}`}
          >
            Contest
            {activeTab === "contest" && <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-900" />}
          </button>
          <button 
            onClick={() => setActiveTab("newsletter")}
            className={`pb-4 text-sm font-bold tracking-widest uppercase transition-colors relative ${activeTab === "newsletter" ? "text-emerald-900" : "text-stone-400 hover:text-stone-600"}`}
          >
            Newsletter
            {activeTab === "newsletter" && <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-900" />}
          </button>
          <button 
            onClick={() => setActiveTab("general")}
            className={`pb-4 text-sm font-bold tracking-widest uppercase transition-colors relative ${activeTab === "general" ? "text-emerald-900" : "text-stone-400 hover:text-stone-600"}`}
          >
            Settings
            {activeTab === "general" && <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-900" />}
          </button>
        </div>

        {activeTab === "posts" ? (
          <>
            <div className="flex justify-between items-center mb-8">
              <h2 className="text-2xl font-serif text-emerald-950">記事一覧</h2>
              <div className="flex gap-4">
                {posts.length === 0 && (
                  <button 
                    onClick={handleMigrate}
                    disabled={isMigrating}
                    className="bg-stone-200 text-stone-700 px-6 py-2 rounded-sm font-bold flex items-center gap-2 hover:bg-stone-300 transition-colors disabled:opacity-50"
                  >
                    {isMigrating ? <div className="animate-spin h-4 w-4 border-2 border-stone-500 border-t-transparent rounded-full" /> : <Plus className="w-4 h-4" />}
                    データを初期化
                  </button>
                )}
                <Link to="/admin/new" className="bg-emerald-700 text-white px-6 py-2 rounded-sm font-bold flex items-center gap-2 hover:bg-emerald-600 transition-colors">
                  <Plus className="w-4 h-4" />
                  新規投稿
                </Link>
              </div>
            </div>

            <div className="bg-white rounded-sm shadow-sm overflow-x-auto border border-stone-200">
              <table className="min-w-[600px] md:min-w-0 w-full text-left">
                <thead className="bg-stone-50 border-b border-stone-200 uppercase text-[10px] font-bold tracking-widest text-emerald-800">
                  <tr>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4">Title</th>
                    <th className="px-6 py-4">Views</th>
                    <th className="px-6 py-4">Date</th>
                    <th className="px-6 py-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-100">
                  {posts.map((post) => (
                    <tr key={post.id} className="hover:bg-stone-50 transition-colors">
                      <td className="px-6 py-4">
                        <span className="bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full text-[10px] font-bold">PUBLISHED</span>
                      </td>
                      <td className="px-6 py-4">
                        <p className="font-bold text-emerald-900 text-sm">{post.title}</p>
                        <p className="text-xs text-gray-400 capitalize">{post.category}</p>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-1 text-sm font-mono text-gray-500">
                          <Eye className="w-3 h-3" />
                          {post.views}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-xs font-mono text-gray-400">{post.date}</td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex justify-end gap-2">
                          <Link to={`/admin/edit/${post.id}`} className="p-2 text-stone-400 hover:text-emerald-600 transition-colors">
                            <Edit className="w-4 h-4" />
                          </Link>
                          <button onClick={() => handleDelete(post.id!)} className="p-2 text-stone-400 hover:text-red-600 transition-colors">
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {posts.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-6 py-12 text-center text-gray-400 font-serif italic">
                        記事がありません。新規投稿から開始してください。
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        ) : activeTab === "slideshow" ? (
          <div className="grid lg:grid-cols-2 gap-12">
            <div className="space-y-6">
              <div className="bg-white p-8 rounded-sm shadow-sm border border-stone-200">
                <h2 className="text-2xl font-serif text-emerald-950 mb-6">スライドショー構成</h2>
                <div className="space-y-4 mb-8">
                  {slideshowImages.map((img, idx) => (
                    <div key={idx} className="flex gap-2 items-start bg-stone-50 p-4 border border-stone-100 rounded-sm">
                      <div className="flex flex-col gap-1">
                        <button 
                          onClick={() => {
                            if (idx === 0) return;
                            const newImages = [...slideshowImages];
                            const temp = newImages[idx];
                            newImages[idx] = newImages[idx - 1];
                            newImages[idx - 1] = temp;
                            setSlideshowImages(newImages);
                          }}
                          disabled={idx === 0}
                          className="p-1 text-stone-400 hover:text-emerald-600 disabled:opacity-20"
                        >
                          <ArrowUp className="w-4 h-4" />
                        </button>
                        <button 
                          onClick={() => {
                            if (idx === slideshowImages.length - 1) return;
                            const newImages = [...slideshowImages];
                            const temp = newImages[idx];
                            newImages[idx] = newImages[idx + 1];
                            newImages[idx + 1] = temp;
                            setSlideshowImages(newImages);
                          }}
                          disabled={idx === slideshowImages.length - 1}
                          className="p-1 text-stone-400 hover:text-emerald-600 disabled:opacity-20"
                        >
                          <ArrowDown className="w-4 h-4" />
                        </button>
                      </div>
                      <div className="flex-grow space-y-3">
                        <input 
                          type="url"
                          value={img.url}
                          onChange={(e) => {
                            const newImages = [...slideshowImages];
                            newImages[idx] = { ...newImages[idx], url: e.target.value };
                            setSlideshowImages(newImages);
                          }}
                          className="w-full p-3 bg-white border border-stone-200 rounded-sm text-xs outline-none focus:ring-1 focus:ring-emerald-600"
                          placeholder="画像URLを入力..."
                        />
                        <textarea
                          rows={2}
                          value={img.caption || ""}
                          onChange={(e) => {
                            const newImages = [...slideshowImages];
                            newImages[idx] = { ...newImages[idx], caption: e.target.value };
                            setSlideshowImages(newImages);
                          }}
                          className="w-full p-3 bg-white border border-stone-200 rounded-sm text-xs outline-none focus:ring-1 focus:ring-emerald-600 resize-none"
                          placeholder="キャプション（任意）"
                        />
                      </div>
                      <button 
                        onClick={() => {
                          const newImages = slideshowImages.filter((_, i) => i !== idx);
                          setSlideshowImages(newImages);
                        }}
                        className="p-3 text-stone-400 hover:text-red-600 transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
                <div className="flex gap-4">
                  <button 
                    onClick={() => setSlideshowImages([...slideshowImages, {url: "", caption: ""}])}
                    className="flex-grow border-2 border-dashed border-stone-200 p-3 text-stone-400 rounded-sm hover:border-emerald-600 hover:text-emerald-600 transition-all text-xs font-bold"
                  >
                    + 画像を追加
                  </button>
                  <button 
                    onClick={handleUpdateSlideshow}
                    disabled={isSavingSlideshow}
                    className="bg-emerald-900 text-white px-8 py-3 rounded-sm font-bold flex items-center gap-2 hover:bg-emerald-800 transition-colors disabled:opacity-50"
                  >
                    {isSavingSlideshow ? <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" /> : <Save className="w-4 h-4" />}
                    保存する
                  </button>
                </div>
              </div>

              <div className="bg-stone-100 p-6 rounded-sm border border-stone-200">
                <h4 className="text-xs font-bold text-stone-500 uppercase tracking-widest mb-3">ヒント</h4>
                <ul className="text-xs text-stone-600 space-y-2 list-disc pl-4 leading-relaxed">
                  <li>Unsplash等の高品質な画像URLを貼り付けてください。</li>
                  <li><span className="text-red-500 font-bold">重要:</span> Google Driveの画像を使用する場合、必ずファイルのアクセス権を<strong>「リンクを知っている全員」</strong>に変更してください。制限されていると画像は表示されません。</li>
                  <li>保存ボタンを押すと即座に反映されます。</li>
                  <li>URLを空にするとプレビューには表示されません。</li>
                </ul>
              </div>
            </div>

            <div className="bg-emerald-950 p-8 rounded-sm shadow-2xl relative overflow-hidden h-fit min-h-[400px]">
              <div className="absolute inset-0 opacity-10">
                <Trophy className="w-full h-full" />
              </div>
              <div className="relative z-10">
                <h3 className="text-white font-serif text-lg mb-6 border-b border-white/10 pb-4">プレビュー</h3>
                <div className="grid grid-cols-2 gap-4">
                  {slideshowImages.map((img, idx) => (
                    img.url && (
                      <div key={idx} className="relative aspect-video rounded-sm overflow-hidden group border border-white/10 bg-black/20">
                        <img src={getDirectImageUrl(img.url)} alt={`Preview ${idx}`} className="w-full h-full object-cover" />
                        <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                          <span className="text-white font-mono text-[10px]">#{idx + 1}</span>
                        </div>
                      </div>
                    )
                  ))}
                  {slideshowImages.filter(u => u.url).length === 0 && (
                    <div className="col-span-2 py-12 flex items-center justify-center text-white/20 text-xs italic">
                      プレビュー画像がありません
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : activeTab === "issue" ? (
          <div className="max-w-4xl mx-auto bg-white p-12 rounded-sm shadow-sm border border-stone-200">
            <div className="flex justify-between items-center mb-10">
              <h2 className="text-3xl font-serif text-emerald-950">最新号情報の管理</h2>
              <button 
                onClick={handleUpdateIssue}
                disabled={isSavingIssue}
                className="bg-emerald-900 text-white px-8 py-3 rounded-sm font-bold flex items-center gap-2 hover:bg-emerald-800 transition-colors disabled:opacity-50"
              >
                {isSavingIssue ? <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" /> : <Save className="w-4 h-4" />}
                保存する
              </button>
            </div>

            <div className="grid md:grid-cols-2 gap-12">
              <div className="space-y-6">
                <div>
                  <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">表紙画像URL</label>
                  <input 
                    type="url"
                    value={latestIssue.coverImage}
                    onChange={(e) => setLatestIssue({...latestIssue, coverImage: e.target.value})}
                    className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-xs"
                    placeholder="https://..."
                  />
                  {latestIssue.coverImage && (
                     <img src={getDirectImageUrl(latestIssue.coverImage)} className="mt-4 w-full rounded border border-stone-100" alt="Cover Preview" />
                  )}
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">タイトル & 号数</label>
                  <textarea 
                    rows={2}
                    value={latestIssue.title}
                    onChange={(e) => setLatestIssue({...latestIssue, title: e.target.value})}
                    className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-sm font-bold"
                    placeholder="隔月刊『風景写真』 2026年 5-6月号"
                  />
                </div>
              </div>

              <div className="space-y-6">
                 <div>
                  <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">価格</label>
                   <input 
                    type="text"
                    value={latestIssue.price}
                    onChange={(e) => setLatestIssue({...latestIssue, price: e.target.value})}
                    className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-sm"
                    placeholder="¥2,200"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">発売日</label>
                   <input 
                    type="text"
                    value={latestIssue.releaseDate}
                    onChange={(e) => setLatestIssue({...latestIssue, releaseDate: e.target.value})}
                    className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-sm"
                    placeholder="2026年2月20日"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">購入URL</label>
                   <input 
                    type="url"
                    value={latestIssue.purchaseUrl}
                    onChange={(e) => setLatestIssue({...latestIssue, purchaseUrl: e.target.value})}
                    className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-sm font-mono text-emerald-700"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">紹介文</label>
                  <textarea 
                    rows={4}
                    value={latestIssue.description}
                    onChange={(e) => setLatestIssue({...latestIssue, description: e.target.value})}
                    className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-xs leading-relaxed"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">主な特集 (3件まで)</label>
                  {latestIssue.features.map((feat, idx) => (
                    <input 
                      key={idx}
                      type="text"
                      value={feat}
                      onChange={(e) => {
                        const newFeats = [...latestIssue.features];
                        newFeats[idx] = e.target.value;
                        setLatestIssue({...latestIssue, features: newFeats});
                      }}
                      className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-xs mb-2"
                      placeholder={`特集 ${idx + 1}`}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : activeTab === "contest" ? (
          <div className="bg-white p-8 md:p-12 rounded-sm shadow-sm border border-stone-200">
            <div className="flex justify-between items-center mb-10">
              <h2 className="text-3xl font-serif text-emerald-950">コンテスト情報の管理</h2>
              <button 
                onClick={handleUpdateContest}
                disabled={isSavingContest}
                className="bg-emerald-900 text-white px-8 py-3 rounded-sm font-bold flex items-center gap-2 hover:bg-emerald-800 transition-colors disabled:opacity-50"
              >
                {isSavingContest ? <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" /> : <Save className="w-4 h-4" />}
                保存する
              </button>
            </div>
            
            <div className="space-y-12">
              <div className="grid md:grid-cols-3 gap-8">
                {contestConfig.contests && contestConfig.contests.map((contest, index) => (
                  <div key={index} className="space-y-4 bg-stone-50 p-6 border border-stone-200 rounded-sm">
                    <h4 className="font-bold text-emerald-900 mb-4">{index + 1}件目</h4>
                    <div>
                      <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">バナー画像URL</label>
                      <input 
                        type="url"
                        value={contest.bannerImage || ""}
                        onChange={(e) => {
                          const newContests = [...contestConfig.contests];
                          newContests[index].bannerImage = e.target.value;
                          setContestConfig({...contestConfig, contests: newContests});
                        }}
                        className="w-full p-2 bg-white border border-stone-200 rounded-sm outline-none text-xs"
                      />
                      {contest.bannerImage && (
                        <div className="mt-2 text-center pb-2">
                          <img src={getDirectImageUrl(contest.bannerImage)} className="w-full h-auto object-cover border border-stone-200 rounded-sm" alt="Preview" />
                        </div>
                      )}
                    </div>
                    <div>
                      <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">タイトル</label>
                      <input 
                        type="text"
                        value={contest.title || ""}
                        onChange={(e) => {
                          const newContests = [...contestConfig.contests];
                          newContests[index].title = e.target.value;
                          setContestConfig({...contestConfig, contests: newContests});
                        }}
                        className="w-full p-2 bg-white border border-stone-200 rounded-sm outline-none text-xs"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">締切</label>
                      <input 
                        type="text"
                        value={contest.deadline || ""}
                        onChange={(e) => {
                          const newContests = [...contestConfig.contests];
                          newContests[index].deadline = e.target.value;
                          setContestConfig({...contestConfig, contests: newContests});
                        }}
                        className="w-full p-2 bg-white border border-stone-200 rounded-sm outline-none text-xs"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">詳細URL</label>
                      <input 
                        type="url"
                        value={contest.url || ""}
                        onChange={(e) => {
                          const newContests = [...contestConfig.contests];
                          newContests[index].url = e.target.value;
                          setContestConfig({...contestConfig, contests: newContests});
                        }}
                        className="w-full p-2 bg-white border border-stone-200 rounded-sm outline-none text-xs"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">概要</label>
                      <textarea 
                        rows={2}
                        value={contest.description || ""}
                        onChange={(e) => {
                          const newContests = [...contestConfig.contests];
                          newContests[index].description = e.target.value;
                          setContestConfig({...contestConfig, contests: newContests});
                        }}
                        className="w-full p-2 bg-white border border-stone-200 rounded-sm outline-none text-xs leading-relaxed"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : activeTab === "seasonalNews" ? (
          <AdminSeasonalNews />
        ) : activeTab === "newsletter" ? (
          <div className="bg-white p-8 md:p-12 rounded-sm shadow-sm border border-stone-200">
            <h2 className="text-3xl font-serif text-emerald-950 mb-8">ニュースレター購読者</h2>
            <div className="bg-stone-50 border border-stone-200 rounded-sm overflow-hidden">
              <table className="w-full text-left">
                <thead className="bg-stone-100 border-b border-stone-200 uppercase text-[10px] font-bold tracking-widest text-emerald-800">
                  <tr>
                    <th className="px-6 py-4">Email</th>
                    <th className="px-6 py-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-100">
                  {subscribers.map((sub) => (
                    <tr key={sub.id} className="hover:bg-stone-50 transition-colors">
                      <td className="px-6 py-4 font-mono text-sm text-emerald-900">{sub.email}</td>
                      <td className="px-6 py-4 text-right">
                        <button 
                          onClick={() => handleDeleteSubscriber(sub.id)}
                          className="p-2 text-stone-400 hover:text-red-600 transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {subscribers.length === 0 && (
                    <tr>
                      <td colSpan={2} className="px-6 py-12 text-center text-gray-400 font-serif italic">
                        購読者がまだいません。
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        ) : activeTab === "general" ? (
          <div className="bg-white p-8 md:p-12 rounded-sm shadow-sm border border-stone-200">
             <div className="flex justify-between items-center mb-10">
              <h2 className="text-3xl font-serif text-emerald-950">一般設定</h2>
              <button 
                onClick={handleUpdateGeneral}
                disabled={isSavingGeneral}
                className="bg-emerald-900 text-white px-8 py-3 rounded-sm font-bold flex items-center gap-2 hover:bg-emerald-800 transition-colors disabled:opacity-50"
              >
                {isSavingGeneral ? <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" /> : <Save className="w-4 h-4" />}
                保存する
              </button>
            </div>
            
            <div className="max-w-md">
              <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">リファレンス既定地域名 (●●に反映されます)</label>
              <input 
                type="text"
                value={generalConfig.refLocation}
                onChange={(e) => setGeneralConfig({...generalConfig, refLocation: e.target.value})}
                className="w-full p-3 bg-stone-50 border border-stone-200 rounded-sm outline-none text-sm font-bold"
                placeholder="東京"
              />
              <p className="mt-2 text-[10px] text-stone-400 leading-relaxed italic">
                リファレンスページの「●●の天気」などの見出しに使用されます。
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-8">
            <div className="bg-white p-8 rounded-sm shadow-sm border border-stone-200">
              <div className="flex justify-between items-center mb-8">
                <h2 className="text-2xl font-serif text-emerald-950">オンライン・ギャラリー構成</h2>
                <button 
                    onClick={handleUpdateGallery}
                    disabled={isSavingGallery}
                    className="bg-emerald-900 text-white px-8 py-3 rounded-sm font-bold flex items-center gap-2 hover:bg-emerald-800 transition-colors disabled:opacity-50"
                  >
                    {isSavingGallery ? <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" /> : <Save className="w-4 h-4" />}
                    保存する
                  </button>
              </div>

              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
                {galleryItems.map((item, idx) => (
                  <div key={idx} className="bg-stone-50 p-4 border border-stone-200 rounded-sm relative group">
                    <button 
                      onClick={() => setGalleryItems(galleryItems.filter((_, i) => i !== idx))}
                      className="absolute top-2 right-2 p-2 bg-white text-stone-400 hover:text-red-500 shadow-sm rounded-full opacity-0 group-hover:opacity-100 transition-opacity z-10"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <div className="aspect-video mb-4 rounded-sm overflow-hidden bg-stone-200">
                      {item.src ? (
                        <img src={getDirectImageUrl(item.src)} alt={item.labelJP} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-stone-400">
                          <Camera className="w-6 h-6" />
                        </div>
                      )}
                    </div>
                    <div className="space-y-3">
                      <input 
                        type="url"
                        placeholder="画像URL"
                        value={item.src}
                        onChange={(e) => {
                          const newItems = [...galleryItems];
                          newItems[idx].src = e.target.value;
                          setGalleryItems(newItems);
                        }}
                        className="w-full p-2 text-xs border border-stone-200 outline-none focus:ring-1 focus:ring-emerald-600 rounded-sm"
                      />
                      <div className="flex gap-2">
                        <input 
                          type="text"
                          placeholder="和名 (例: 春)"
                          value={item.labelJP}
                          onChange={(e) => {
                            const newItems = [...galleryItems];
                            newItems[idx].labelJP = e.target.value;
                            setGalleryItems(newItems);
                          }}
                          className="w-1/2 p-2 text-xs border border-stone-200 outline-none focus:ring-1 focus:ring-emerald-600 rounded-sm font-bold"
                        />
                        <input 
                          type="text"
                          placeholder="英名 (例: SPRING)"
                          value={item.labelEN}
                          onChange={(e) => {
                            const newItems = [...galleryItems];
                            newItems[idx].labelEN = e.target.value;
                            setGalleryItems(newItems);
                          }}
                          className="w-1/2 p-2 text-xs border border-stone-200 outline-none focus:ring-1 focus:ring-emerald-600 rounded-sm font-mono"
                        />
                      </div>
                    </div>
                  </div>
                ))}
                <button 
                  onClick={() => setGalleryItems([...galleryItems, { src: "", labelJP: "", labelEN: "" }])}
                  className="aspect-video border-2 border-dashed border-stone-200 rounded-sm flex flex-col items-center justify-center text-stone-400 hover:border-emerald-600 hover:text-emerald-600 transition-all gap-2"
                >
                  <Plus className="w-6 h-6" />
                  <span className="text-xs font-bold uppercase tracking-widest">アイテムを追加</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const AdminPostEditor = () => {
  const { id } = useParams();
  const { user, isAdmin, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [postData, setPostData] = useState({
    title: '',
    category: 'お知らせ',
    date: new Date().toLocaleDateString('ja-JP'),
    excerpt: '',
    content: '',
    image: '',
  });

  useEffect(() => {
    if (!authLoading && !isAdmin) navigate('/login');
    
    if (id) {
      setLoading(true);
      const fetchPost = async () => {
        const docRef = realDoc(realDb, "posts", id);
        let docSnap;
        try {
          docSnap = await realGetDoc(docRef);
        } catch (err) {
          console.error(err);
        }
        if (docSnap && docSnap.exists()) {
          const data = docSnap.data();
          setPostData({
            title: data.title,
            category: data.category,
            date: data.date,
            excerpt: data.excerpt,
            content: data.content,
            image: data.image
          });
        }
        setLoading(false);
      };
      fetchPost();
    }
  }, [id, isAdmin, authLoading, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user) return;
    setLoading(true);
    
    const pId = id || Math.random().toString(36).substring(7);
    
    const payload = {
      ...postData,
      authorId: user.uid,
      updatedAt: realServerTimestamp(),
      ...(id ? {} : { views: 0, createdAt: realServerTimestamp() })
    };

    try {
      if (id) {
        await realSetDoc(realDoc(realDb, "posts", id), payload, { merge: true });
      } else {
        await realSetDoc(realDoc(realDb, "posts", pId), payload);
      }
      navigate('/admin');
    } catch (err) {
      console.error(err);
      alert('保存中にエラーが発生しました。');
    } finally {
      setLoading(false);
    }
  };

  if (authLoading || !isAdmin) return null;

  return (
    <div className="min-h-screen bg-stone-50 pb-24 font-sans">
      <nav className="bg-white border-b border-stone-200 py-4 px-8 sticky top-0 z-50 flex justify-between items-center">
        <div className="flex items-center gap-4">
          <Link to="/admin" className="p-2 hover:bg-stone-50 rounded-full transition-colors">
            <ArrowLeft className="w-5 h-5 text-emerald-950" />
          </Link>
          <h1 className="text-xl font-serif text-emerald-950">{id ? '記事を編集' : '新規記事作成'}</h1>
        </div>
        <button 
          onClick={handleSubmit}
          disabled={loading}
          className="bg-emerald-900 text-white px-8 py-2 rounded-sm font-bold flex items-center gap-2 hover:bg-emerald-800 transition-colors disabled:opacity-50"
        >
          {loading ? <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" /> : <Save className="w-4 h-4" />}
          公開する
        </button>
      </nav>

      <div className="max-w-4xl mx-auto p-8 grid lg:grid-cols-3 gap-8">
        <form className="lg:col-span-2 space-y-6" onSubmit={handleSubmit}>
          <div className="bg-white p-8 rounded-sm shadow-sm border border-stone-200 space-y-6">
            <div>
              <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">タイトル</label>
              <input 
                type="text" 
                value={postData.title}
                onChange={e => setPostData({...postData, title: e.target.value})}
                required
                className="w-full text-2xl font-bold text-emerald-950 border-b border-stone-200 focus:border-emerald-600 outline-none pb-2"
                placeholder="記事のタイトルを入力..."
              />
            </div>
            
            <div>
              <label className="block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">本文 (Markdown形式)</label>
              <textarea 
                rows={15}
                value={postData.content}
                onChange={e => setPostData({...postData, content: e.target.value})}
                required
                className="w-full p-4 bg-stone-50 border border-stone-200 rounded-sm focus:ring-1 focus:ring-emerald-600 outline-none font-mono text-sm leading-relaxed"
                placeholder="内容を執筆してください..."
              />
            </div>
          </div>
        </form>

        <aside className="space-y-6">
          <div className="bg-white p-6 rounded-sm shadow-sm border border-stone-200 space-y-4">
            <h3 className="font-bold text-emerald-900 mb-2 pb-2 border-b border-stone-100">設定</h3>
            
            <div>
              <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">カテゴリー</label>
              <select 
                value={postData.category}
                onChange={e => setPostData({...postData, category: e.target.value})}
                className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-sm"
              >
                <option>お知らせ</option>
                <option>イベント</option>
                <option>雑誌・書籍</option>
                <option>ギャラリー</option>
              </select>
            </div>

            <div>
              <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">表示用日付</label>
              <input 
                type="text" 
                value={postData.date}
                onChange={e => setPostData({...postData, date: e.target.value})}
                className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-sm"
              />
            </div>

            <div>
              <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">アイキャッチ画像URL</label>
              <input 
                type="url" 
                value={postData.image}
                onChange={e => setPostData({...postData, image: e.target.value})}
                required
                className="w-full p-2 bg-stone-50 border border-stone-200 rounded-sm outline-none text-sm mb-2"
                placeholder="https://images.unsplash.com/..."
              />
              {postData.image && (
                <img src={getDirectImageUrl(postData.image)} className="w-full aspect-video object-cover rounded-sm border border-stone-200" alt="Preview" />
              )}
            </div>
          </div>

          <div className="bg-white p-6 rounded-sm shadow-sm border border-stone-200">
            <label className="block text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">概要 (一覧表示用)</label>
            <textarea 
              rows={4}
              value={postData.excerpt}
              onChange={e => setPostData({...postData, excerpt: e.target.value})}
              required
              className="w-full p-3 bg-stone-50 border border-stone-200 rounded-sm outline-none text-xs leading-relaxed"
              placeholder="記事の要約を入力..."
            />
          </div>
        </aside>
      </div>
    </div>
  );
};

/**
 * Mystery Secret Portal Component
 */
const SecretPortal = ({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) => {
  const [passcode, setPasscode] = useState("");
  const navigate = useNavigate();

  const handleDigit = (digit: string) => {
    if (passcode.length < 4) {
      const newPass = passcode + digit;
      setPasscode(newPass);
      if (newPass === "2971") {
        setTimeout(() => {
          onClose();
          navigate("/admin");
        }, 500);
      } else if (newPass.length === 4) {
        setTimeout(() => setPasscode(""), 500);
      }
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/95 backdrop-blur-xl"
        >
          <div className="max-w-xs w-full text-center">
            <motion.div
              initial={{ scale: 0.8, y: 20 }}
              animate={{ scale: 1, y: 0 }}
              className="mb-12"
            >
              <Camera className="w-12 h-12 text-emerald-500 mx-auto mb-4" />
              <h2 className="text-white font-serif text-xl tracking-widest uppercase mb-2">Secret Entrance</h2>
              <p className="text-emerald-500/50 text-[10px] tracking-[0.4em] uppercase">Enter the passcode</p>
            </motion.div>

            <div className="grid grid-cols-3 gap-4 mb-12">
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, "", 0, "clear"].map((val, i) => (
                <button
                  key={i}
                  onClick={() => val === "clear" ? setPasscode("") : (val !== "" ? handleDigit(val.toString()) : null)}
                  className={`aspect-square rounded-full border border-white/10 flex items-center justify-center text-xl transition-all ${val === "" ? "opacity-0 cursor-default" : "hover:bg-white/10 hover:border-emerald-500 text-white"}`}
                >
                  {val === "clear" ? <X className="w-5 h-5" /> : val}
                </button>
              ))}
            </div>

            <div className="flex justify-center gap-4">
              {[0, 1, 2, 3].map((i) => (
                <div 
                  key={i}
                  className={`w-3 h-3 rounded-full border border-emerald-500/30 transition-all ${passcode.length > i ? "bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)]" : ""}`}
                />
              ))}
            </div>

            <button 
              onClick={onClose}
              className="mt-16 text-white/30 hover:text-white uppercase text-[10px] tracking-widest transition-colors"
            >
              Close Window
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

const ScrollToTop = () => {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
};

export default function App() {
  const [activeModal, setActiveModal] = useState<"issue" | "subscription" | null>(null);
  const [isSecretOpen, setIsSecretOpen] = useState(false);
  const [isLineAuthenticated, setIsLineAuthenticated] = useState(false);

  if (!isLineAuthenticated) {
    return (
      <div className="min-h-screen bg-[#111] flex flex-col items-center justify-center p-6 text-center font-sans tracking-wide relative overflow-hidden">
        {/* Background decorative elements */}
        <div className="absolute top-0 right-0 w-64 h-64 bg-emerald-900/20 rounded-full blur-[80px] -z-10"></div>
        <div className="absolute bottom-0 left-0 w-80 h-80 bg-emerald-800/10 rounded-full blur-[100px] -z-10"></div>
        
        <BookOpen className="w-12 h-12 md:w-16 md:h-16 text-emerald-400 mb-6 drop-shadow-md" />
        <h1 className="text-2xl md:text-3xl font-bold text-white mb-8 leading-tight drop-shadow-sm">
          撮影リファレンス［LINE］<br/>
          <span className="text-lg md:text-2xl font-normal text-emerald-200 mt-2 inline-block">（会員限定コンテンツ）</span>
        </h1>
        
        <div className="bg-white/5 border border-white/10 rounded-2xl p-6 md:p-8 backdrop-blur-sm max-w-xl mx-auto mb-10 shadow-2xl">
          <p className="text-gray-300 mb-6 text-[15px] md:text-base leading-[1.8] text-left">
            「撮影リファレンス［LINE］」は、風景写真公式LINEアカウントをご登録いただいている会員様限定のポータルサービスです。
          </p>
          <p className="text-gray-300 mb-6 text-[15px] md:text-base leading-[1.8] text-left">
            一般の天気予報や潮汐表では絶対に手に入らない、プロ直伝の「現地のトチカン（サバイバル警告・無風時の水鏡確率・潮位によるアプローチ限界時間）」を網羅した、写真家専用の現場インフラとなっています。
          </p>
          <p className="text-gray-300 text-[15px] md:text-base leading-[1.8] text-left">
            以下のボタンから公式LINEを友だち追加（無料）していただくことで、今すぐこの画面の全機能（撮影地検索・気象・タイドグラフ・トチカン連携）をご利用いただけます。
          </p>
        </div>
        
        <button 
          onClick={() => setIsLineAuthenticated(true)}
          className="bg-[#06C755] text-white font-bold text-[15px] md:text-lg py-4 px-8 md:px-12 rounded-full shadow-[0_4px_14px_0_rgba(6,199,85,0.39)] hover:shadow-[0_6px_20px_rgba(6,199,85,0.23)] hover:bg-[#05b34c] transition-all duration-300 flex items-center justify-center gap-3 w-full max-w-md group"
        >
          <svg viewBox="0 0 24 24" className="w-6 h-6 fill-current group-hover:scale-110 transition-transform" xmlns="http://www.w3.org/2000/svg">
            <path d="M24 10.304c0-5.369-5.383-9.738-12-9.738-6.616 0-12 4.369-12 9.738 0 4.814 4.269 8.846 10.036 9.608.391.084.922.258 1.057.592.122.302.079.771.038 1.083l-.164 1.02c-.045.301-.24 1.186 1.049.645 1.291-.539 6.916-4.078 9.436-6.967C23.176 14.394 24 12.443 24 10.304" />
          </svg>
          LINEで今すぐ利用する（友だち追加）
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white font-sans text-gray-900 selection:bg-emerald-100 selection:text-emerald-900">
      <ScrollToTop />
      <Navbar />
      <AnimatePresence mode="wait">
        <Routes>
          <Route path="/" element={
            <main>
              <Hero onIssueClick={() => setActiveModal("issue")} onSubClick={() => setActiveModal("subscription")} />
              <NewsSection />
              <MagazineSection />
              {/* <GallerySection /> */}
              {/* <ShopSection /> */}
              <ContestSection />
              <ContactSection />
            </main>
          } />
          <Route path="/blog" element={<BlogListPage />} />
          <Route path="/blog/:id" element={<BlogPostPage />} />
          <Route path="/archive" element={<ArchivePage />} />
          <Route path="/reference" element={<ReferencePage />} />
          <Route path="/reference/summary" element={<AISummaryPage />} />
          <Route path="/database" element={<ContestDatabasePage />} />
          <Route path="/import" element={<ImportFirebasePage />} />
          <Route path="/debug-images" element={<ImageDebugger />} />
          
          {/* Admin Routes */}
          <Route path="/login" element={<AdminLogin />} />
          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="/admin/new" element={<AdminPostEditor />} />
          <Route path="/admin/edit/:id" element={<AdminPostEditor />} />
        </Routes>
      </AnimatePresence>
      <Footer onSecretPortal={() => setIsSecretOpen(true)} onOpenSubscription={() => setActiveModal("subscription")} />
      
      <SecretPortal isOpen={isSecretOpen} onClose={() => setIsSecretOpen(false)} />

      {/* Modals */}
      <AnimatePresence>
        {activeModal === "issue" && (
          <MagazineModal onClose={() => setActiveModal(null)} />
        )}

        {activeModal === "subscription" && (
          <Modal onClose={() => setActiveModal(null)}>
            <div className="p-8">
              <div className="max-w-2xl mx-auto text-center">
                <BookOpen className="w-12 h-12 text-emerald-700 mx-auto mb-6" />
                <h2 className="text-3xl font-serif text-gray-900 mb-4">定期購読のご案内</h2>
                <p className="text-gray-600 mb-8">
                  『風景写真』を毎号確実にお手元へ。定期購読なら、発売日当日（または前日）にお届けいたします。
                </p>
                
                <div className="grid md:grid-cols-2 gap-6 mb-10 text-left">
                  <div className="bg-emerald-50 p-6 rounded-sm">
                    <h4 className="font-bold text-emerald-900 mb-2">1年間（6冊）コース</h4>
                    <p className="text-sm text-gray-600 mb-4">通常価格よりお得な特別価格でご提供。</p>
                    <p className="text-xl font-bold text-emerald-900">¥12,000 <span className="text-xs font-normal text-gray-500">(送料込)</span></p>
                  </div>
                  <div className="bg-emerald-50 p-6 rounded-sm">
                    <h4 className="font-bold text-emerald-900 mb-2">購読特典</h4>
                    <ul className="text-xs text-gray-600 space-y-2">
                      <li>・特製オリジナルカレンダー進呈</li>
                      <li>・バックナンバー電子版閲覧権</li>
                      <li>・主催イベントの優先案内</li>
                    </ul>
                  </div>
                </div>

                <a 
                  href="https://fukeinews.exblog.jp/32466186/" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="inline-block bg-emerald-900 text-white px-12 py-4 font-bold hover:bg-emerald-800 transition-colors shadow-lg"
                >
                  詳細・お申し込みはこちら
                </a>
              </div>
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}

const ImageDebugger = () => {
  const indices = Array.from({ length: 30 }, (_, i) => i);
  return (
    <div className="p-8 bg-gray-100 min-h-screen">
      <h1 className="text-3xl font-bold mb-8">Image Index Debugger</h1>
      <p className="mb-4 text-gray-600">This page displays all potential uploaded images (input_file_0.png to input_file_29.png). Please check which index corresponds to your logos.</p>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {indices.map((i) => (
          <div key={i} className="bg-white p-2 rounded shadow-sm border border-gray-200">
            <p className="font-mono text-[10px] mb-1">Index {i}: input_file_{i}.png</p>
            <div className="aspect-video bg-gray-200 flex items-center justify-center overflow-hidden rounded">
              <img 
                src={`/input_file_${i}.png`} 
                alt={`Index ${i}`} 
                className="max-w-full max-h-full object-contain"
                referrerPolicy="no-referrer"
              />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-8">
        <Link to="/" className="inline-block bg-gray-800 text-white px-6 py-2 rounded">
          ← Back to Home
        </Link>
      </div>
    </div>
  );
};

const Modal = ({ children, onClose }: { children: ReactNode; onClose: () => void }) => (
  <motion.div 
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    exit={{ opacity: 0 }}
    className="fixed inset-0 z-[100] flex items-center justify-center p-6 bg-emerald-950/40 backdrop-blur-sm"
    onClick={onClose}
  >
    <motion.div 
      initial={{ scale: 0.9, y: 20 }}
      animate={{ scale: 1, y: 0 }}
      exit={{ scale: 0.9, y: 20 }}
      className="bg-white w-full max-w-4xl max-h-[90vh] overflow-y-auto relative rounded-sm shadow-2xl"
      onClick={(e) => e.stopPropagation()}
    >
      <button 
        onClick={onClose}
        className="absolute top-4 right-4 text-gray-400 hover:text-gray-900 transition-colors z-10"
      >
        <X className="w-6 h-6" />
      </button>
      {children}
    </motion.div>
  </motion.div>
);

const MagazineModal = ({ onClose }: { onClose: () => void }) => {
  const [issue, setIssue] = useState<LatestIssueConfig | null>(null);

  useEffect(() => {
    const unsub = realOnSnapshot(realDoc(realDb, "settings", "latest_issue"), (snapshot) => {
      if (snapshot.exists()) {
        setIssue(snapshot.data() as LatestIssueConfig);
      }
    }, (error) => console.error("MagazineModal onSnapshot error:", error));
    return () => unsub();
  }, []);

  const defaultIssue: LatestIssueConfig = {
    coverImage: "https://img16.shop-pro.jp/PA01095/035/product/191545024.png?cmsp_timestamp=20260421165639",
    title: "隔月刊『風景写真』\n2026年 5-6月号",
    description: "初夏、それは鮮やかな緑色を背に色とりどりの花々が咲き競う「花の季節」です。今号の『風景写真』では撮れ高に期待膨らむ自然園・ガーデンに焦点を当て、日本の花風景の魅力に迫ります。",
    purchaseUrl: "https://fukei-shashin.shop-pro.jp/?pid=191545024",
    price: "¥2,200",
    releaseDate: "2026年4月20日",
    features: ["心ゆくまで花楽園―初夏の自然園・ガーデンを撮る", "林惣一「こころ葉」／星野翔「律」", "チームチャンピオンズカップ2026 長野大会"],
    updatedAt: null
  };

  const data = {
    coverImage: issue?.coverImage || defaultIssue.coverImage,
    title: issue?.title || defaultIssue.title,
    description: issue?.description || defaultIssue.description,
    purchaseUrl: issue?.purchaseUrl || defaultIssue.purchaseUrl,
    price: issue?.price || defaultIssue.price,
    releaseDate: issue?.releaseDate || defaultIssue.releaseDate,
    features: Array.isArray(issue?.features) && issue.features.length > 0 ? issue.features : defaultIssue.features
  };

  return (
    <Modal onClose={onClose}>
      <div className="p-8">
        <div className="grid md:grid-cols-2 gap-12">
          <div>
            <img 
              src={getDirectImageUrl(data.coverImage)} 
              alt="Latest Issue" 
              className="w-full shadow-2xl rounded-sm"
              referrerPolicy="no-referrer"
              onError={(e) => {
                const target = e.target as HTMLImageElement;
                target.src = "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?q=80&w=800&auto=format&fit=crop";
              }}
            />
          </div>
          <div>
            <span className="text-emerald-700 font-bold tracking-widest text-xs mb-2 block">NEW RELEASE</span>
            <h2 className="text-3xl font-serif text-gray-900 mb-4 whitespace-pre-wrap">{data.title}</h2>
            <p className="text-2xl font-bold text-emerald-900 mb-6">{data.price} <span className="text-sm font-normal text-gray-500">(税込)</span></p>
            
            <div className="space-y-6 mb-8">
              <div>
                <h4 className="font-bold text-gray-900 mb-2 border-b border-gray-100 pb-2">主な内容</h4>
                <ul className="text-sm text-gray-600 space-y-2">
                  {data.features.filter(f => f.trim()).map((f, i) => (
                    <li key={i}>・{f}</li>
                  ))}
                </ul>
              </div>
            </div>

            <a 
              href={data.purchaseUrl} 
              target="_blank" 
              rel="noopener noreferrer"
              className="block w-full bg-emerald-900 text-white text-center py-4 font-bold hover:bg-emerald-800 transition-colors shadow-lg"
            >
              公式ショップで購入する
            </a>
          </div>
        </div>
      </div>
    </Modal>
  );
};
