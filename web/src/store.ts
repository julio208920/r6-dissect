import { create } from "zustand";

export type ModuleName = "Dashboard" | "Match History" | "Operator Analytics" | "Team Analytics" | "School Selection";

interface ClientState {
  activeModule: ModuleName;
  season: string;
  accent: string;
  selectedSchool: string;
  setModule: (module: ModuleName) => void;
  setSeason: (season: string) => void;
  setBrand: (school: string, accent: string) => void;
}

export const useClientStore = create<ClientState>((set) => ({
  activeModule: "Dashboard",
  season: "current",
  accent: "#d49353",
  selectedSchool: "",
  setModule: (activeModule) => set({ activeModule }),
  setSeason: (season) => set({ season }),
  setBrand: (selectedSchool, accent) => set({ selectedSchool, accent }),
}));