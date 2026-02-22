import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { VpnPoolTab } from './_tabs/VpnPoolTab';
import { VpnAgentsTab } from './_tabs/VpnAgentsTab';
import { VpnBatchTab } from './_tabs/VpnBatchTab';
import { VpnHealthTab } from './_tabs/VpnHealthTab';

export default function VpnPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">VPN Management</h1>
      <Tabs defaultValue="pool">
        <TabsList>
          <TabsTrigger value="pool">IP Pool</TabsTrigger>
          <TabsTrigger value="agents">Agents</TabsTrigger>
          <TabsTrigger value="batch">Batch Ops</TabsTrigger>
          <TabsTrigger value="health">Health</TabsTrigger>
        </TabsList>
        <TabsContent value="pool">
          <VpnPoolTab />
        </TabsContent>
        <TabsContent value="agents">
          <VpnAgentsTab />
        </TabsContent>
        <TabsContent value="batch">
          <VpnBatchTab />
        </TabsContent>
        <TabsContent value="health">
          <VpnHealthTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
