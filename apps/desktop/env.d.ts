export {};

declare global {
  interface Window {
    companion?: {
      getServiceStatus(): Promise<{
        state: "starting" | "running" | "failed";
        detail: string;
        apiBaseUrl: string;
      }>;
    };
  }
}
