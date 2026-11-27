import backgrounds_home from "@midnight/backgrounds/home@3x.png";
import backgrounds_chat from "@midnight/backgrounds/chat@3x.png";
import backgrounds_settings from "@midnight/backgrounds/settings@3x.png";
import backgrounds_login from "@midnight/backgrounds/login@3x.png";
import characters_idle from "@midnight/characters/idle@3x.png";
import characters_happy from "@midnight/characters/happy@3x.png";
import characters_shy from "@midnight/characters/shy@3x.png";
import characters_curious from "@midnight/characters/curious@3x.png";
import characters_angry from "@midnight/characters/angry@3x.png";
import characters_sad from "@midnight/characters/sad@3x.png";
import characters_sleeping from "@midnight/characters/sleeping@3x.png";
import characters_affectionate from "@midnight/characters/affectionate@3x.png";
import avatars_idle from "@midnight/avatars/idle@3x.png";
import avatars_happy from "@midnight/avatars/happy@3x.png";
import avatars_shy from "@midnight/avatars/shy@3x.png";
import avatars_curious from "@midnight/avatars/curious@3x.png";
import avatars_angry from "@midnight/avatars/angry@3x.png";
import avatars_sad from "@midnight/avatars/sad@3x.png";
import avatars_sleeping from "@midnight/avatars/sleeping@3x.png";
import avatars_affectionate from "@midnight/avatars/affectionate@3x.png";
import avatars_default from "@midnight/avatars/default@3x.png";
import decorations_star from "@midnight/decorations/star@3x.png";
import decorations_crescent from "@midnight/decorations/crescent@3x.png";
import icons_chat_active from "@midnight/icons/chat-active@3x.png";
import icons_chat_inactive from "@midnight/icons/chat-inactive@3x.png";
import icons_settings_active from "@midnight/icons/settings-active@3x.png";
import icons_settings_inactive from "@midnight/icons/settings-inactive@3x.png";
import icons_account from "@midnight/icons/account@3x.png";
import icons_add from "@midnight/icons/add@3x.png";
import icons_back from "@midnight/icons/back@3x.png";
import icons_more from "@midnight/icons/more@3x.png";
import icons_send from "@midnight/icons/send@3x.png";

// Optional art from the animation pack. An absent pack leaves the static curious pose available.
const curiousAnimation = import.meta.glob<string>(
  ["@midnight/animations/curious/preview.png", "@midnight/animations/curious/curious.apng", "@midnight/animations/curious/frames/cat-00.png"],
  { eager: true, import: "default", query: "?url" },
);
const curiousAssets = Object.entries(curiousAnimation);
export const midnightAssets = {
  backgrounds: {
    "home": backgrounds_home,
    "chat": backgrounds_chat,
    "settings": backgrounds_settings,
    "login": backgrounds_login,
  },
  characters: {
    "idle": characters_idle,
    "happy": characters_happy,
    "shy": characters_shy,
    "curious": characters_curious,
    "angry": characters_angry,
    "sad": characters_sad,
    "sleeping": characters_sleeping,
    "affectionate": characters_affectionate,
  },
  avatars: {
    "idle": avatars_idle,
    "happy": avatars_happy,
    "shy": avatars_shy,
    "curious": avatars_curious,
    "angry": avatars_angry,
    "sad": avatars_sad,
    "sleeping": avatars_sleeping,
    "affectionate": avatars_affectionate,
    "default": avatars_default,
  },
  decorations: {
    "star": decorations_star,
    "crescent": decorations_crescent,
  },
  icons: {
    "chat-active": icons_chat_active,
    "chat-inactive": icons_chat_inactive,
    "settings-active": icons_settings_active,
    "settings-inactive": icons_settings_inactive,
    "account": icons_account,
    "add": icons_add,
    "back": icons_back,
    "more": icons_more,
    "send": icons_send,
  },
  curiousMotion: curiousAssets.find(([file]) => /\/(curious\.apng|preview\.png)$/.test(file))?.[1],
  curiousStill: curiousAssets.find(([file]) => file.endsWith("/cat-00.png"))?.[1],
} as const;

export type MidnightPage = keyof typeof midnightAssets.backgrounds;
export type MidnightState = keyof typeof midnightAssets.characters;

const visualStates = new Map<string, MidnightState>([
  ["joy", "happy"], ["happy", "happy"], ["excitement", "happy"], ["开心", "happy"], ["兴奋", "happy"],
  ["affection", "affectionate"], ["affectionate", "affectionate"], ["亲密", "affectionate"], ["亲昵", "affectionate"],
  ["longing", "sad"], ["sadness", "sad"], ["hurt", "sad"], ["sad", "sad"], ["想念", "sad"], ["难过", "sad"], ["委屈", "sad"],
  ["anger", "angry"], ["jealousy", "angry"], ["angry", "angry"], ["愤怒", "angry"], ["嫉妒", "angry"],
  ["anxiety", "shy"], ["shy", "shy"], ["不安", "shy"], ["害羞", "shy"],
  ["attentive", "curious"], ["engaged", "curious"], ["curious", "curious"], ["专注", "curious"], ["投入", "curious"], ["好奇", "curious"],
  ["sleeping", "sleeping"], ["睡眠", "sleeping"],
]);

export function midnightState(emotion: string): MidnightState {
  return visualStates.get(emotion.trim().toLowerCase()) ?? "idle";
}

export const midnightStatus: Record<MidnightState, string> = {
  idle: "今晚很安静",
  happy: "此刻很开心",
  shy: "有一点害羞",
  curious: "正好奇地看着你",
  angry: "现在有点不悦",
  sad: "此刻有些低落",
  sleeping: "正在休息",
  affectionate: "想和你靠近一点",
};
