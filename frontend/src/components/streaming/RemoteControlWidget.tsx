import React, { useState } from "react";
import { Power, Home, ArrowLeft, MoreVertical, Type, Send, Volume2, Volume1, VolumeX } from "lucide-react";
import { Button } from "@/src/shared/ui/button";
import { Input } from "@/components/ui/input";

interface RemoteControlWidgetProps {
    onSendKey: (keyCode: number) => void;
    onSendText: (text: string) => void;
}

// Android KeyCodes
const KEYCODE_HOME = 3;
const KEYCODE_BACK = 4;
const KEYCODE_POWER = 26;
const KEYCODE_VOLUME_UP = 24;
const KEYCODE_VOLUME_DOWN = 25;
const KEYCODE_MENU = 82;

export function RemoteControlWidget({ onSendKey, onSendText }: RemoteControlWidgetProps) {
    const [textInput, setTextInput] = useState("");
    const [showKeyboard, setShowKeyboard] = useState(false);

    const handleSendText = (e: React.FormEvent) => {
        e.preventDefault();
        if (textInput.trim()) {
            onSendText(textInput);
            setTextInput("");
            setShowKeyboard(false);
        }
    };

    return (
        <div className="absolute top-2 right-2 flex flex-col gap-2 items-end z-20">

            {/* Keyboard Input Popover */}
            {showKeyboard && (
                <form onSubmit={handleSendText} className="flex items-center gap-1 bg-muted/90 backdrop-blur-md p-1.5 rounded-sm border border-border mb-1 animate-in slide-in-from-right-2">
                    <Input
                        autoFocus
                        value={textInput}
                        onChange={(e) => setTextInput(e.target.value)}
                        placeholder="[ TYPE TO DEVICE ]"
                        className="h-7 text-[10px] uppercase font-mono bg-background border-border min-w-[150px] placeholder:text-muted-foreground"
                    />
                    <Button type="submit" size="icon" className="h-7 w-7 bg-primary/20 text-primary hover:bg-primary/40 rounded-sm shrink-0">
                        <Send className="w-3.5 h-3.5" />
                    </Button>
                </form>
            )}

            {/* Main KVM Toolbar */}
            <div className="flex flex-col gap-1 bg-muted/80 backdrop-blur-md p-1.5 rounded-sm border border-border shadow-lg">
                <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => onSendKey(KEYCODE_POWER)}
                    className="h-8 w-8 text-destructive hover:bg-destructive/20 hover:text-destructive rounded-sm"
                    title="Power / Wake"
                >
                    <Power className="w-4 h-4" />
                </Button>

                <div className="w-full h-px bg-[#333] my-1" />

                <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => onSendKey(KEYCODE_VOLUME_UP)}
                    className="h-8 w-8 text-muted-foreground hover:bg-[#333] hover:text-foreground rounded-sm"
                    title="Volume Up"
                >
                    <Volume2 className="w-4 h-4" />
                </Button>
                <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => onSendKey(KEYCODE_VOLUME_DOWN)}
                    className="h-8 w-8 text-muted-foreground hover:bg-[#333] hover:text-foreground rounded-sm"
                    title="Volume Down"
                >
                    <Volume1 className="w-4 h-4" />
                </Button>

                <div className="w-full h-px bg-[#333] my-1" />

                <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setShowKeyboard(!showKeyboard)}
                    className={`h-8 w-8 rounded-sm ${showKeyboard ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:bg-[#333] hover:text-foreground'}`}
                    title="Keyboard Input"
                >
                    <Type className="w-4 h-4" />
                </Button>

                <div className="w-full h-px bg-border my-1" />

                <div className="flex flex-col gap-0.5">
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onSendKey(KEYCODE_MENU)}
                        className="h-8 w-8 text-muted-foreground hover:bg-background hover:text-foreground rounded-sm"
                        title="Menu"
                    >
                        <MoreVertical className="w-4 h-4" />
                    </Button>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onSendKey(KEYCODE_HOME)}
                        className="h-8 w-8 text-muted-foreground hover:bg-background hover:text-foreground rounded-sm"
                        title="Home"
                    >
                        <Home className="w-4 h-4" />
                    </Button>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onSendKey(KEYCODE_BACK)}
                        className="h-8 w-8 text-muted-foreground hover:bg-background hover:text-foreground rounded-sm"
                        title="Back"
                    >
                        <ArrowLeft className="w-4 h-4" />
                    </Button>
                </div>
            </div>
        </div>
    );
}
