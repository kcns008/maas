/* Copyright 2015 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * MAAS Nodes Manager
 *
 * Manages all of the nodes in the browser. This manager is used for the
 * node listing and the node view page. The manager uses the RegionConnection
 * to load the nodes, update the nodes, and listen for notification events
 * about nodes.
 */

angular.module('MAAS').factory(
    'NodesManager',
    ['$q', '$rootScope', 'RegionConnection', 'Manager', function(
            $q, $rootScope, RegionConnection, Manager) {

        function NodesManager() {
            Manager.call(this);

            this._pk = "system_id";
            this._handler = "node";
            this._metadataAttributes = [
                "status",
                "owner",
                "tags"
            ];

            // Listen for notify events for the node object.
            var self = this;
            RegionConnection.registerNotifier("node", function(action, data) {
                self.onNotify(action, data);
            });
        }

        NodesManager.prototype = new Manager();

        // Create a node.
        NodesManager.prototype.create = function(node) {
            // We don't add the item to the list because a NOTIFY event will
            // add the node to the list. Adding it here will cause angular to
            // complain because the same object exist in the list.
            return RegionConnection.callMethod("node.create", node);
        };

        // Perform the action on the node.
        NodesManager.prototype.performAction = function(node, action, extra) {
            if(!angular.isObject(extra)) {
                extra = {};
            }
            return RegionConnection.callMethod("node.action", {
                "system_id": node.system_id,
                "action": action,
                "extra": extra
                });
        };

        return new NodesManager();
    }]);